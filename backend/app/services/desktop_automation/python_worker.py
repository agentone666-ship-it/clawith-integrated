"""Pure-stdlib worker sent into an ephemeral, networkless Python container."""

WORKER_SOURCE = r"""
import ast,json,sys,traceback,types
payload=json.loads(sys.stdin.readline())
logs=[];log_bytes=0;steps=[];bindings={};lines={}
class SecretRef:
 def __init__(self,name):self.name=name
 def __str__(self):raise TypeError('敏感参数只能直接传给 ui.type_text，不可计算、拼接或输出')
 def __repr__(self):return '<secret parameter>'
def log(*values,**kwargs):
 global log_bytes
 text=' '.join(str(v)for v in values)
 if log_bytes+len(text.encode())>8192:raise ValueError('print 输出超过 8 KiB，请缩小诊断输出')
 logs.append(text);log_bytes+=len(text.encode())
class DesktopPlan:
 def window(self,app,title):return {'app':app,'title':title}
 def add(self,action,**kw):
  if len(steps)>=120:raise ValueError('桌面动作超过 120 步，请缩小单次任务')
  ident='py_%04d'%(len(steps)+1);s={'id':ident,'action':action,**kw}
  if isinstance(s.get('text'),SecretRef):bindings[ident]=s['text'].name;s['text']='<secret>'
  frame=sys._getframe(1)
  while frame and frame.f_code.co_filename!='user_script.py':frame=frame.f_back
  if frame:lines[ident]=frame.f_lineno
  steps.append(s)
 def launch(self,app,label=''):self.add('launch_app',app=app,label=label)
 def click(self,x,y,*,target,label=''):self.add('click',x=x,y=y,target=target,label=label)
 def double_click(self,x,y,*,target,label=''):self.add('double_click',x=x,y=y,target=target,label=label)
 def right_click(self,x,y,*,target,label=''):self.add('right_click',x=x,y=y,target=target,label=label)
 def type_text(self,text,*,target,label=''):self.add('type_text',text=text,target=target,label=label)
 def key(self,key,*,target,modifiers=(),label=''):self.add('hotkey'if modifiers else'press_key',key=key,modifiers=list(modifiers),target=target,label=label)
 def hotkey(self,*keys,target,label=''):
  if len(keys)<2:raise ValueError('ui.hotkey 至少需要修饰键和普通键')
  self.key(keys[-1],target=target,modifiers=keys[:-1],label=label)
 def scroll(self,direction,amount=3,*,target,label=''):self.add('scroll',direction=direction,amount=amount,target=target,label=label)
 def assert_text(self,text,*,target,timeout_seconds=8,label=''):self.add('assert_text',text=text,target=target,timeout_seconds=timeout_seconds,label=label)
try:
 tree=ast.parse(payload['source'],filename='user_script.py')
 if sum(1 for _ in ast.walk(tree))>12000:raise ValueError('脚本结构过大，请拆分任务')
 allowed={'automation','decimal','math','json','re','datetime','itertools','statistics'}
 for n in ast.walk(tree):
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   names=[x.name for x in n.names]if isinstance(n,ast.Import)else[n.module]
   if any(m not in allowed for m in names):raise ValueError('只允许 automation 和纯计算库；不能使用文件、网络、进程或其他模型')
  if isinstance(n,ast.Attribute)and n.attr.startswith('_'):raise ValueError('不支持私有属性或运行时反射')
  if isinstance(n,ast.Name)and(n.id.startswith('__')or n.id in {'open','exec','eval','compile','globals','locals','getattr','setattr','vars','input'}):raise ValueError('只通过 ui 编排桌面操作，不支持文件或动态执行 API')
 module=types.ModuleType('automation');module.ui=DesktopPlan();module.inputs=dict(payload['inputs'])
 for name in payload['secret_parameters']:module.inputs[name]=SecretRef(name)
 sys.modules['automation']=module
 ns={'__name__':'__main__','print':log}
 exec(compile(tree,'user_script.py','exec'),ns)
 result={'ok':True,'plan':{'steps':steps,'secret_bindings':bindings,'source_lines':lines},'stdout':'\n'.join(logs)}
except BaseException as e:
 frames=traceback.extract_tb(e.__traceback__)
 line=getattr(e,'lineno',None)or next((f.lineno for f in reversed(frames)if f.filename=='user_script.py'),None)
 result={'ok':False,'diagnostic':{'code':type(e).__name__,'message':str(e)[:1200],'line':line},'stdout':'\n'.join(logs)}
sys.__stdout__.write(json.dumps(result,ensure_ascii=False)+'\n')
"""
