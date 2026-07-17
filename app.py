import base64, json, mimetypes, os, queue, threading, time, urllib.request, urllib.error, urllib.parse, uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL import Image, ImageTk, ImageOps

FIXED_PROMPT = "最高优先级：锁定参考图服装的原始几何比例。必须逐像素级参考原图版型，衣长与肩宽的比例必须和参考图完全相同，胸宽、腰宽、下摆宽度、袖长、袖肥、肩线位置均不得改变。禁止横向扩张，禁止加宽衣身，禁止加宽肩部，禁止放大胸围，禁止放大腰围，禁止放大下摆，禁止把修身版改成宽松版，禁止把长款改成短款，禁止任何透视变形、拉伸或膨胀。若无法判断，宁可让衣服更修长、更窄，也绝对不要变宽变胖。服装中轴线垂直，正面自然平铺，完整呈现，不裁切。输出使用3:4竖版构图，服装高度约占画布70%，宽度严格按原图长宽比自然呈现，左右各保留至少20%纯白留白，上下各保留至少12%留白。无缝纯白背景，垂直俯拍，专业电商无影柔光，浅淡自然接触阴影，面料纹理、花色和颜色真实准确，衣物平整干净。无模特、无人台、无衣架、无道具、无杂物、无文字、无水印、无额外Logo，写实电商商品摄影。"
APPDATA = Path(os.getenv("APPDATA", Path.home())) / "服装白底图助手"
CONFIG = APPDATA / "config.json"
DEFAULT = {
    "provider":"runninghub", "runninghub_key":"", "cangyuan_key":"", "suoxie_key":"", "custom_key":"",
    "endpoint":"https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image", "model":"1k",
    "custom_endpoint":"", "custom_model":"", "output":str(Path.home()/"Desktop"/"AI出图"), "custom_prompt":""
}
CANGYUAN_MODELS = [
    ("gpt-image-2", "GPT Image 2 基础版 — ¥0.015/张"), ("gpt-image-2-1k", "GPT Image 2 · 1K — ¥0.025/张"),
    ("gpt-image-2-2k", "GPT Image 2 · 2K — ¥0.05/张"), ("gpt-image-2-4k", "GPT Image 2 · 4K — ¥0.08/张"),
    ("nano-banana-pro-1k", "Nano Banana Pro · 1K — ¥0.08/张"), ("nano-banana-pro-2k", "Nano Banana Pro · 2K — ¥0.10/张"),
    ("nano-banana-pro-4k", "Nano Banana Pro · 4K — ¥0.149/张"), ("nano-banana2-1k", "Nano Banana 2 · 1K — ¥0.059/张"),
    ("nano-banana2-2k", "Nano Banana 2 · 2K — ¥0.08/张"), ("nano-banana2-4k", "Nano Banana 2 · 4K — ¥0.12/张")]

def load_config():
    try:
        c={**DEFAULT, **json.loads(CONFIG.read_text("utf-8"))}
        if not c.get("runninghub_key") and c.get("api_key"): c["runninghub_key"]=c["api_key"]
        return c
    except Exception: return DEFAULT.copy()
def save_config(c):
    APPDATA.mkdir(parents=True, exist_ok=True); CONFIG.write_text(json.dumps(c,ensure_ascii=False,indent=2),"utf-8")
def request_json(url,key,body=None,method="POST",timeout=600):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
    req=urllib.request.Request(url,data,{"Content-Type":"application/json","Authorization":"Bearer "+key},method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode(errors="replace")[:1200])
def multipart_edit(url,key,path,prompt,model):
    boundary="AIImageTool-"+uuid.uuid4().hex; raw=Path(path).read_bytes(); mime=mimetypes.guess_type(path)[0] or "image/jpeg"; chunks=[]
    def field(name,value): chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    field("model",model);field("prompt",prompt);field("size","1024x1536");field("n","1")
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{Path(path).name}"\r\nContent-Type: {mime}\r\n\r\n'.encode());chunks.append(raw);chunks.append(f'\r\n--{boundary}--\r\n'.encode())
    req=urllib.request.Request(url,b"".join(chunks),{"Content-Type":f"multipart/form-data; boundary={boundary}","Authorization":"Bearer "+key},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=600) as r:return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode(errors="replace")[:1200])
def at_path(obj,path):
    try:
        for part in path.split("."): obj=obj[int(part)] if isinstance(obj,list) else obj[part]
        return obj
    except Exception:return None
def save_result(value,source,out):
    if not isinstance(value,str) or not value:raise RuntimeError("接口没有返回图片")
    if value.startswith("http"):
        data=urllib.request.urlopen(value,timeout=300).read();suffix=Path(urllib.parse.urlparse(value).path).suffix or ".png"
    else:
        value=value.split(",",1)[-1];data=base64.b64decode(value);suffix=".png"
    out=Path(out);out.mkdir(parents=True,exist_ok=True);target=out/f"{Path(source).stem}_AI_{int(time.time()*1000)}{suffix}";target.write_bytes(data);return str(target)

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__();self.title("服装白底图助手 - Windows");self.geometry("1240x820");self.minsize(1000,680)
        self.cfg=load_config();self.files=[];self.results=[];self.history={};self.processed=set();self.running=set();self.events=queue.Queue();self.visible=[];self.left_photos={};self.right_photos={}
        self.build();self.after(100,self.poll)
    def build(self):
        style=ttk.Style(self);style.configure("Thumb.Treeview",rowheight=106,font=("Microsoft YaHei UI",10))
        root=ttk.Frame(self,padding=20);root.pack(fill="both",expand=True)
        ttk.Label(root,text="服装白底图助手",font=("Microsoft YaHei UI",22,"bold")).pack(anchor="w");ttk.Label(root,text="拖入左侧后自动生成；双击缩略图可预览。",foreground="#666").pack(anchor="w",pady=(2,12))
        controls=ttk.Frame(root);controls.pack(fill="x",pady=(0,12));ttk.Label(controls,text="提示词：").pack(side="left");self.mode=tk.StringVar(value="默认服装白底（固定）")
        box=ttk.Combobox(controls,textvariable=self.mode,values=["默认服装白底（固定）","自定义提示词"],state="readonly",width=22);box.pack(side="left");box.bind("<<ComboboxSelected>>",self.mode_change)
        ttk.Button(controls,text="API 设置",command=self.settings).pack(side="right");self.out=tk.StringVar(value=self.cfg["output"]);ttk.Button(controls,text="选择导出目录",command=self.choose_out).pack(side="right",padx=6);ttk.Entry(controls,textvariable=self.out,width=34).pack(side="right")
        self.prompt=tk.Text(root,height=5,wrap="word",font=("Microsoft YaHei UI",10));self.prompt.pack(fill="x",pady=(0,12));self.prompt.insert("1.0",FIXED_PROMPT);self.prompt.config(state="disabled",background="#f3f3f3")
        pane=ttk.Panedwindow(root,orient="horizontal");pane.pack(fill="both",expand=True);left=ttk.LabelFrame(pane,text="待生成图片（可拖入）",padding=10);right=ttk.LabelFrame(pane,text="已生成图片",padding=10);pane.add(left,weight=1);pane.add(right,weight=1)
        self.left=ttk.Treeview(left,show="tree",style="Thumb.Treeview",selectmode="browse");self.left.column("#0",width=470,stretch=True);self.left.pack(fill="both",expand=True);self.left.drop_target_register(DND_FILES);self.left.dnd_bind("<<Drop>>",self.drop)
        lb=ttk.Frame(left);lb.pack(fill="x",pady=(8,0))
        for text,cmd in [("添加图片",self.add),("预览",lambda:self.preview(False)),("重新生成",self.regenerate),("移除",self.remove),("清空",self.clear)]:ttk.Button(lb,text=text,command=cmd).pack(side="left",padx=2)
        self.right=ttk.Treeview(right,show="tree",style="Thumb.Treeview",selectmode="browse");self.right.column("#0",width=470,stretch=True);self.right.pack(fill="both",expand=True)
        rb=ttk.Frame(right);rb.pack(fill="x",pady=(8,0))
        for text,cmd in [("预览",lambda:self.preview(True)),("历史生成",self.show_history),("全部结果",self.show_all),("打开文件夹",self.open_folder)]:ttk.Button(rb,text=text,command=cmd).pack(side="left",padx=2)
        self.left.bind("<Double-1>",lambda e:self.preview(False));self.right.bind("<Double-1>",lambda e:self.preview(True))
        foot=ttk.Frame(root);foot.pack(fill="x",pady=(12,0));self.status=ttk.Label(foot,text="准备就绪");self.status.pack(side="left");self.progress=ttk.Progressbar(foot,length=260);self.progress.pack(side="right")
    def thumbnail(self,path):
        try:
            img=ImageOps.exif_transpose(Image.open(path)).convert("RGB");img.thumbnail((92,92));canvas=Image.new("RGB",(96,96),"white");canvas.paste(img,((96-img.width)//2,(96-img.height)//2));return ImageTk.PhotoImage(canvas)
        except Exception:return None
    def refresh_left(self):
        self.left.delete(*self.left.get_children());self.left_photos.clear()
        for i,p in enumerate(self.files):
            ph=self.thumbnail(p);iid=str(i);self.left_photos[iid]=ph;state="生成中…" if p in self.running else ("已生成" if p in self.processed else "待生成");self.left.insert("", "end",iid=iid,text=f"  {Path(p).name}\n  {state}",image=ph)
    def refresh_right(self,items=None):
        self.visible=list(self.results if items is None else items);self.right.delete(*self.right.get_children());self.right_photos.clear()
        for i,p in enumerate(self.visible):
            ph=self.thumbnail(p);iid=str(i);self.right_photos[iid]=ph;self.right.insert("","end",iid=iid,text=f"  {Path(p).name}",image=ph)
    def selected_path(self,result=False):
        box=self.right if result else self.left;sel=box.selection()
        if not sel:return None
        i=int(sel[0]);items=self.visible if result else self.files;return items[i] if i<len(items) else None
    def mode_change(self,e=None):
        self.prompt.config(state="normal")
        if self.mode.get().startswith("默认"):self.prompt.delete("1.0","end");self.prompt.insert("1.0",FIXED_PROMPT);self.prompt.config(state="disabled",background="#f3f3f3")
        else:self.prompt.delete("1.0","end");self.prompt.insert("1.0",self.cfg["custom_prompt"]);self.prompt.config(background="white");self.prompt.focus()
    def choose_out(self):
        p=filedialog.askdirectory(initialdir=self.out.get());
        if p:self.out.set(p)
    def settings(self):
        w=tk.Toplevel(self);w.title("API 设置");w.geometry("680x470");w.transient(self);f=ttk.Frame(w,padding=20);f.pack(fill="both",expand=True)
        provider=tk.StringVar(value=self.cfg.get("provider","runninghub"));endpoint=tk.StringVar();key=tk.StringVar();model=tk.StringVar();model_values=[]
        ttk.Label(f,text="API 服务商",font=("Microsoft YaHei UI",10,"bold")).pack(anchor="w");pc=ttk.Combobox(f,textvariable=provider,values=["runninghub","cangyuan","suoxie","custom"],state="readonly");pc.pack(fill="x",pady=(3,12))
        ttk.Label(f,text="接口地址",font=("Microsoft YaHei UI",10,"bold")).pack(anchor="w");ee=ttk.Entry(f,textvariable=endpoint);ee.pack(fill="x",pady=(3,12));ttk.Label(f,text="API Key",font=("Microsoft YaHei UI",10,"bold")).pack(anchor="w");ke=ttk.Entry(f,textvariable=key,show="●");ke.pack(fill="x",pady=(3,12))
        ttk.Label(f,text="模型 / 分辨率（沧元价格为参考价）",font=("Microsoft YaHei UI",10,"bold")).pack(anchor="w");mc=ttk.Combobox(f,textvariable=model);mc.pack(fill="x",pady=(3,8));hint=ttk.Label(f,text="",foreground="#666",wraplength=620);hint.pack(anchor="w")
        def change(*_):
            nonlocal model_values
            p=provider.get();model_values=[]
            if p=="runninghub":endpoint.set("https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image");key.set(self.cfg.get("runninghub_key",""));model_values=[("1k","1k"),("2k","2k"),("4k","4k")];hint.config(text="RunningHub 图生图")
            elif p=="cangyuan":endpoint.set("https://ai.cangyuansuanli.cn/v1/images/generations");key.set(self.cfg.get("cangyuan_key",""));model_values=CANGYUAN_MODELS;hint.config(text="选择模型时已标注当前参考价格")
            elif p=="suoxie":endpoint.set("https://suoxie.codes/v1/images/edits");key.set(self.cfg.get("suoxie_key",""));model.set(self.cfg.get("suoxie_model","gpt-image-2"));mc.config(values=[],state="normal");hint.config(text="使用 images/edits 上传参考图；模型以该 Key 的 /v1/models 为准");return
            else:endpoint.set(self.cfg.get("custom_endpoint",""));key.set(self.cfg.get("custom_key",""));model.set(self.cfg.get("custom_model",""));mc.config(values=[],state="normal");hint.config(text="通用 OpenAI 兼容格式，只需填写地址、Key、模型");return
            labels=[x[1] for x in model_values];mc.config(values=labels,state="readonly");saved=self.cfg.get("model","");idx=next((i for i,x in enumerate(model_values) if x[0]==saved),0);mc.current(idx)
        pc.bind("<<ComboboxSelected>>",change);change()
        def ok():
            p=provider.get();self.cfg["provider"]=p;self.cfg["endpoint"]=endpoint.get().strip();self.cfg[p+"_key"]=key.get().strip();self.cfg["model"]=(model_values[mc.current()][0] if model_values and mc.current()>=0 else model.get().strip())
            if p=="suoxie":self.cfg["suoxie_model"]=self.cfg["model"]
            if p=="custom":self.cfg["custom_endpoint"]=self.cfg["endpoint"];self.cfg["custom_model"]=self.cfg["model"]
            save_config(self.cfg);w.destroy();self.status.config(text="API 设置已保存")
        ttk.Button(f,text="保存设置",command=ok).pack(anchor="e",pady=(20,0))
    def add(self):self.add_paths(filedialog.askopenfilenames(filetypes=[("图片","*.png *.jpg *.jpeg *.webp")]))
    def drop(self,e):self.add_paths(self.tk.splitlist(e.data))
    def add_paths(self,paths):
        new=[]
        for p in paths:
            p=str(Path(p))
            if Path(p).suffix.lower() in (".png",".jpg",".jpeg",".webp") and p not in self.files:self.files.append(p);new.append(p)
        self.refresh_left()
        for p in new:self.generate(p)
    def remove(self):
        p=self.selected_path()
        if not p:return
        self.files.remove(p);self.processed.discard(p);self.refresh_left()
    def clear(self):self.files.clear();self.processed.clear();self.refresh_left()
    def regenerate(self):
        p=self.selected_path()
        if p:self.processed.discard(p);self.generate(p)
    def generate(self,p):
        if p in self.processed or p in self.running:return
        provider=self.cfg.get("provider","runninghub");key=self.cfg.get(provider+"_key","")
        if not key and provider!="custom":messagebox.showwarning("缺少 API Key","请先在 API 设置中填写当前服务商的 API Key。");return
        prompt=self.prompt.get("1.0","end").strip() if self.mode.get().startswith("自定义") else FIXED_PROMPT
        if self.mode.get().startswith("自定义"):self.cfg["custom_prompt"]=prompt;save_config(self.cfg)
        self.running.add(p);self.refresh_left();threading.Thread(target=self.worker,args=(p,prompt),daemon=True).start()
    def worker(self,p,prompt):
        try:
            provider=self.cfg.get("provider","runninghub");key=self.cfg.get(provider+"_key","");model=self.cfg.get("model","1k");endpoint=self.cfg.get("endpoint","");self.events.put(("status",f"正在提交：{Path(p).name}"))
            raw=Path(p).read_bytes();mime=mimetypes.guess_type(p)[0] or "image/jpeg";uri=f"data:{mime};base64,"+base64.b64encode(raw).decode()
            if provider=="runninghub":
                data=request_json(endpoint,key,{"prompt":prompt,"imageUrls":[uri],"aspectRatio":"3:4","resolution":model});task=data.get("taskId")
                if not task:raise RuntimeError(data.get("errorMessage") or "未返回 taskId")
                for _ in range(200):
                    time.sleep(3);q=request_json("https://www.runninghub.cn/openapi/v2/query",key,{"taskId":task});self.events.put(("status",f"{q.get('status','')}：{Path(p).name}"))
                    if q.get("status")=="SUCCESS":data=q;break
                    if q.get("status")=="FAILED":raise RuntimeError(q.get("errorMessage") or "生成失败")
                value=at_path(data,"results.0.url")
            elif provider=="cangyuan":
                size="4K" if "4k" in model.lower() else ("2K" if "2k" in model.lower() else "1K");data=request_json(endpoint,key,{"model":model,"prompt":prompt,"aspect_ratio":"3:4","output_resolution":size,"image_size":size,"image":uri,"n":1,"quality":"medium","stream":False,"response_format":"url"});value=at_path(data,"data.0.url") or at_path(data,"data.0.b64_json")
                task=data.get("task_id") or data.get("id")
                if not value and task:
                    for _ in range(200):
                        time.sleep(4);q=request_json(endpoint.rstrip("/")+"/"+str(task),key,None,"GET");self.events.put(("status",f"{q.get('status','')}：{Path(p).name}"));value=at_path(q,"data.0.url") or at_path(q,"data.0.b64_json")
                        if value:break
                        if q.get("status")=="failed":raise RuntimeError(str(q.get("error") or "生成失败"))
            elif provider=="suoxie":data=multipart_edit(endpoint,key,p,prompt,model);value=at_path(data,"data.0.url") or at_path(data,"data.0.b64_json")
            else:data=request_json(endpoint,key,{"model":model,"prompt":prompt,"image":uri,"aspect_ratio":"3:4","n":1,"response_format":"url"});value=at_path(data,"data.0.url") or at_path(data,"data.0.b64_json")
            target=save_result(value,p,self.out.get());self.events.put(("done",p,target))
        except Exception as e:self.events.put(("error",p,str(e)))
    def poll(self):
        try:
            while True:
                e=self.events.get_nowait()
                if e[0]=="status":self.status.config(text=e[1])
                elif e[0]=="done":
                    p,r=e[1:];self.running.discard(p);self.processed.add(p);self.results.append(r);self.history.setdefault(p,[]).append(r);self.refresh_left();self.refresh_right();self.status.config(text="生成完成："+Path(r).name)
                elif e[0]=="error":self.running.discard(e[1]);self.refresh_left();self.status.config(text="失败："+e[2]);messagebox.showerror("生成失败",e[2])
        except queue.Empty:pass
        self.after(100,self.poll)
    def show_all(self):self.refresh_right()
    def show_history(self):
        p=self.selected_path()
        if not p:messagebox.showinfo("提示","请先选中左侧原图");return
        self.refresh_right(self.history.get(p,[]))
    def preview(self,result):
        p=self.selected_path(result)
        if not p:return
        w=tk.Toplevel(self);w.title(Path(p).name);img=ImageOps.exif_transpose(Image.open(p));img.thumbnail((900,750));photo=ImageTk.PhotoImage(img);lab=ttk.Label(w,image=photo);lab.image=photo;lab.pack(padx=10,pady=10)
    def open_folder(self):Path(self.out.get()).mkdir(parents=True,exist_ok=True);os.startfile(self.out.get())

if __name__=="__main__":App().mainloop()
