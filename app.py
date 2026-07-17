import base64, json, mimetypes, os, queue, threading, time, urllib.request, urllib.error
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL import Image, ImageTk

FIXED_PROMPT = "最高优先级：锁定参考图服装的原始几何比例。必须逐像素级参考原图版型，衣长与肩宽的比例必须和参考图完全相同，胸宽、腰宽、下摆宽度、袖长、袖肥、肩线位置均不得改变。禁止横向扩张，禁止加宽衣身，禁止加宽肩部，禁止放大胸围，禁止放大腰围，禁止放大下摆，禁止把修身版改成宽松版，禁止把长款改成短款，禁止任何透视变形、拉伸或膨胀。若无法判断，宁可让衣服更修长、更窄，也绝对不要变宽变胖。服装中轴线垂直，正面自然平铺，完整呈现，不裁切。输出使用3:4竖版构图，服装高度约占画布70%，宽度严格按原图长宽比自然呈现，左右各保留至少20%纯白留白，上下各保留至少12%留白。无缝纯白背景，垂直俯拍，专业电商无影柔光，浅淡自然接触阴影，面料纹理、花色和颜色真实准确，衣物平整干净。无模特、无人台、无衣架、无道具、无杂物、无文字、无水印、无额外Logo，写实电商商品摄影。"
APPDATA = Path(os.getenv("APPDATA", Path.home())) / "服装白底图助手"
CONFIG = APPDATA / "config.json"
DEFAULT = {"api_key":"", "endpoint":"https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image", "resolution":"1k", "output":str(Path.home()/"Desktop"/"AI出图"), "custom_prompt":""}

def load_config():
    try: return {**DEFAULT, **json.loads(CONFIG.read_text("utf-8"))}
    except Exception: return DEFAULT.copy()
def save_config(c):
    APPDATA.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=2), "utf-8")
def post_json(url, key, body, timeout=300):
    req=urllib.request.Request(url, json.dumps(body,ensure_ascii=False).encode(), {"Content-Type":"application/json","Authorization":"Bearer "+key}, method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode(errors="replace")[:800])

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__(); self.title("服装白底图助手 - Windows"); self.geometry("1180x780"); self.minsize(980,650)
        self.cfg=load_config(); self.files=[]; self.results=[]; self.history={}; self.processed=set(); self.events=queue.Queue(); self.running=set(); self.thumbs=[]
        self.build(); self.after(100,self.poll)
    def build(self):
        root=ttk.Frame(self,padding=20); root.pack(fill="both",expand=True)
        ttk.Label(root,text="服装白底图助手",font=("Microsoft YaHei UI",22,"bold")).pack(anchor="w")
        ttk.Label(root,text="将图片拖入左侧后自动生成，结果显示在右侧。",foreground="#666").pack(anchor="w",pady=(2,12))
        controls=ttk.Frame(root); controls.pack(fill="x",pady=(0,12))
        ttk.Label(controls,text="提示词：").pack(side="left"); self.mode=tk.StringVar(value="默认服装白底（固定）")
        box=ttk.Combobox(controls,textvariable=self.mode,values=["默认服装白底（固定）","自定义提示词"],state="readonly",width=22); box.pack(side="left"); box.bind("<<ComboboxSelected>>",self.mode_change)
        ttk.Button(controls,text="API 设置",command=self.settings).pack(side="right")
        self.out=tk.StringVar(value=self.cfg["output"]); ttk.Button(controls,text="选择导出目录",command=self.choose_out).pack(side="right",padx=6); ttk.Entry(controls,textvariable=self.out,width=34).pack(side="right")
        self.prompt=tk.Text(root,height=5,wrap="word",font=("Microsoft YaHei UI",10)); self.prompt.pack(fill="x",pady=(0,12)); self.prompt.insert("1.0",FIXED_PROMPT); self.prompt.config(state="disabled",background="#f3f3f3")
        pane=ttk.Panedwindow(root,orient="horizontal"); pane.pack(fill="both",expand=True)
        left=ttk.LabelFrame(pane,text="待生成图片（可拖入）",padding=10); right=ttk.LabelFrame(pane,text="已生成图片",padding=10); pane.add(left,weight=1); pane.add(right,weight=1)
        self.left=tk.Listbox(left,selectmode="browse",font=("Microsoft YaHei UI",10)); self.left.pack(fill="both",expand=True); self.left.drop_target_register(DND_FILES); self.left.dnd_bind("<<Drop>>",self.drop)
        lb=ttk.Frame(left);lb.pack(fill="x",pady=(8,0));
        for text,cmd in [("添加图片",self.add),("预览",lambda:self.preview(False)),("重新生成",self.regenerate),("移除",self.remove),("清空",self.clear)]: ttk.Button(lb,text=text,command=cmd).pack(side="left",padx=2)
        self.right=tk.Listbox(right,selectmode="browse",font=("Microsoft YaHei UI",10)); self.right.pack(fill="both",expand=True)
        rb=ttk.Frame(right);rb.pack(fill="x",pady=(8,0));
        for text,cmd in [("预览",lambda:self.preview(True)),("历史生成",self.show_history),("全部结果",self.show_all),("打开文件夹",self.open_folder)]: ttk.Button(rb,text=text,command=cmd).pack(side="left",padx=2)
        self.left.bind("<Double-1>",lambda e:self.preview(False)); self.right.bind("<Double-1>",lambda e:self.preview(True))
        foot=ttk.Frame(root);foot.pack(fill="x",pady=(12,0));self.status=ttk.Label(foot,text="准备就绪");self.status.pack(side="left");self.progress=ttk.Progressbar(foot,length=260);self.progress.pack(side="right")
    def mode_change(self,e=None):
        self.prompt.config(state="normal")
        if self.mode.get().startswith("默认"): self.cfg["custom_prompt"]=self.prompt.get("1.0","end").strip() if self.prompt.cget("background")!="#f3f3f3" else self.cfg["custom_prompt"]; self.prompt.delete("1.0","end");self.prompt.insert("1.0",FIXED_PROMPT);self.prompt.config(state="disabled",background="#f3f3f3")
        else: self.prompt.delete("1.0","end");self.prompt.insert("1.0",self.cfg["custom_prompt"]);self.prompt.config(background="white");self.prompt.focus()
    def choose_out(self):
        p=filedialog.askdirectory(initialdir=self.out.get());
        if p:self.out.set(p)
    def settings(self):
        w=tk.Toplevel(self);w.title("RunningHub API 设置");w.geometry("620x330");f=ttk.Frame(w,padding=20);f.pack(fill="both",expand=True); vals={}
        for label,key,secret in [("接口地址","endpoint",False),("RunningHub API Key","api_key",True),("输出分辨率（1k / 2k / 4k）","resolution",False)]:
            ttk.Label(f,text=label).pack(anchor="w");v=tk.StringVar(value=self.cfg[key]);vals[key]=v;ttk.Entry(f,textvariable=v,show="●" if secret else "").pack(fill="x",pady=(3,10))
        def ok():
            for k,v in vals.items():self.cfg[k]=v.get().strip()
            save_config(self.cfg);w.destroy();self.status.config(text="API 设置已保存")
        ttk.Button(f,text="保存设置",command=ok).pack(anchor="e")
    def add(self): self.add_paths(filedialog.askopenfilenames(filetypes=[("图片","*.png *.jpg *.jpeg *.webp")]))
    def drop(self,e): self.add_paths(self.tk.splitlist(e.data))
    def add_paths(self,paths):
        new=[]
        for p in paths:
            p=str(Path(p));
            if Path(p).suffix.lower() in (".png",".jpg",".jpeg",".webp") and p not in self.files:self.files.append(p);self.left.insert("end",Path(p).name);new.append(p)
        for p in new:self.generate(p)
    def remove(self):
        if not self.left.curselection():return
        i=self.left.curselection()[0];p=self.files.pop(i);self.processed.discard(p);self.left.delete(i)
    def clear(self): self.files.clear();self.processed.clear();self.left.delete(0,"end")
    def regenerate(self):
        if not self.left.curselection():return
        p=self.files[self.left.curselection()[0]];self.processed.discard(p);self.generate(p)
    def generate(self,p):
        if p in self.processed or p in self.running:return
        if not self.cfg["api_key"]:messagebox.showwarning("缺少 API Key","请先打开 API 设置，填写 RunningHub API Key。");return
        if self.mode.get().startswith("自定义"):self.cfg["custom_prompt"]=self.prompt.get("1.0","end").strip();save_config(self.cfg);prompt=self.cfg["custom_prompt"]
        else:prompt=FIXED_PROMPT
        self.running.add(p);threading.Thread(target=self.worker,args=(p,prompt),daemon=True).start()
    def worker(self,p,prompt):
        try:
            self.events.put(("status","正在提交："+Path(p).name)); raw=Path(p).read_bytes();mime=mimetypes.guess_type(p)[0] or "image/jpeg";uri=f"data:{mime};base64,"+base64.b64encode(raw).decode()
            data=post_json(self.cfg["endpoint"],self.cfg["api_key"],{"prompt":prompt,"imageUrls":[uri],"aspectRatio":"3:4","resolution":self.cfg["resolution"]});task=data.get("taskId")
            if not task:raise RuntimeError(data.get("errorMessage") or "未返回 taskId")
            result=None
            for _ in range(200):
                time.sleep(3);q=post_json("https://www.runninghub.cn/openapi/v2/query",self.cfg["api_key"],{"taskId":task});self.events.put(("status",f"{q.get('status','')}：{Path(p).name}"))
                if q.get("status")=="SUCCESS":result=q;break
                if q.get("status")=="FAILED":raise RuntimeError(q.get("errorMessage") or "生成失败")
            if not result or not result.get("results"):raise RuntimeError("等待结果超时")
            item=result["results"][0];out=Path(self.out.get());out.mkdir(parents=True,exist_ok=True);target=out/f"{Path(p).stem}_AI_{int(time.time()*1000)}.{item.get('outputType','png')}";target.write_bytes(urllib.request.urlopen(item["url"],timeout=180).read());self.events.put(("done",p,str(target)))
        except Exception as e:self.events.put(("error",p,str(e)))
    def poll(self):
        try:
            while True:
                e=self.events.get_nowait()
                if e[0]=="status":self.status.config(text=e[1])
                elif e[0]=="done":
                    p,r=e[1:];self.running.discard(p);self.processed.add(p);self.results.append(r);self.history.setdefault(p,[]).append(r);self.show_all();self.status.config(text="生成完成："+Path(r).name)
                elif e[0]=="error":self.running.discard(e[1]);self.status.config(text="失败："+e[2]);messagebox.showerror("生成失败",e[2])
        except queue.Empty:pass
        self.after(100,self.poll)
    def show_all(self): self.right.delete(0,"end");[self.right.insert("end",Path(x).name) for x in self.results];self.visible=list(self.results)
    def show_history(self):
        if not self.left.curselection():messagebox.showinfo("提示","请先选中左侧原图");return
        h=self.history.get(self.files[self.left.curselection()[0]],[]);self.right.delete(0,"end");[self.right.insert("end",Path(x).name) for x in h];self.visible=list(h)
    def preview(self,result):
        box=self.right if result else self.left
        if not box.curselection():return
        p=(getattr(self,"visible",self.results) if result else self.files)[box.curselection()[0]];w=tk.Toplevel(self);w.title(Path(p).name);img=Image.open(p);img.thumbnail((900,750));photo=ImageTk.PhotoImage(img);lab=ttk.Label(w,image=photo);lab.image=photo;lab.pack(padx=10,pady=10)
    def open_folder(self): os.startfile(self.out.get())

if __name__=="__main__": App().mainloop()
