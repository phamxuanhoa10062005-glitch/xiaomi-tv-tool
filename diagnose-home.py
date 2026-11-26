#!/usr/bin/env python3
"""Read-only HOME diagnostics; never install/disable apps, write settings or reboot.
The report stays on the phone. No automatic uploads, credential/key reads, or serial-number collection.
"""
import datetime,hashlib,ipaddress,json,pathlib,re,shutil,subprocess,sys
ROOT=pathlib.Path.home()/'.xiaomi-tv-tool'
PACKAGE='com.spocky.projengmenu'
PORT='15039'
READ_COMMANDS={
 'model':['getprop','ro.product.model'],
 'firmware':['getprop','ro.build.display.id'],
 'android':['getprop','ro.build.version.release'],
 'sdk':['getprop','ro.build.version.sdk'],
 'hardware':['getprop','ro.hardware'],
 'board':['getprop','ro.board.platform'],
 'soc':['getprop','ro.soc.model'],
 'boot_completed':['getprop','sys.boot_completed'],
 'user_unlocked_property':['getprop','sys.user.0.ce_available'],
 'current_user':['am','get-current-user'],
 'home_candidates':['cmd','package','query-activities','--brief','--components','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME'],
 'home':['cmd','package','resolve-activity','--brief','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME'],
 'home_default_only':['cmd','package','resolve-activity','--brief','--query-flags','0x10000','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME'],
 'home_with_default_category':['cmd','package','resolve-activity','--brief','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME','-c','android.intent.category.DEFAULT'],
 'projectivy_home':['cmd','package','resolve-activity','--brief','--user','0','-a','android.intent.action.MAIN','-c','android.intent.category.HOME','-p',PACKAGE],
 'disabled_packages':['pm','list','packages','-d','--user','0'],
 'projectivy_package':['dumpsys','package',PACKAGE],
 'projectivy_path':['pm','path','--user','0',PACKAGE],
 'accessibility_enabled':['settings','get','secure','accessibility_enabled'],
 'accessibility_services':['settings','get','secure','enabled_accessibility_services'],
 'accessibility_runtime':['dumpsys','accessibility'],
 'assistant':['settings','get','secure','assistant'],
 'voice_service':['settings','get','secure','voice_interaction_service'],
 'recognition':['settings','get','secure','voice_recognition_service'],
 'roles':['dumpsys','role'],
 'activity':['dumpsys','activity','activities'],
}
def endpoint(value):
 p=value.strip().split(':')
 if len(p) not in (1,2):raise ValueError('IP khong hop le')
 ip=ipaddress.IPv4Address(p[0]);port=int(p[1]) if len(p)==2 else 5555
 if not ip.is_private or not 1<=port<=65535:raise ValueError('Dung IP noi bo cua TV va cong hop le')
 return str(ip)+':'+str(port)
def component(text):
 return next((s.strip() for s in reversed(text.splitlines()) if re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+',s.strip())),text.strip()[:200] or '(trong)')
def redact(rows,address):
 cleaned=[]
 for row in rows:
  r=dict(row)
  if r.get('args',[])[:2]==['shell','getprop'] and r['args'][-1]=='ro.serialno':continue
  if r.get('kind')=='snapshot':
   data=dict(r.get('data',{}));data.pop('serial',None);r['data']=data
  if r.get('target'):r['target']='TV'
  cleaned.append(json.loads(json.dumps(r,ensure_ascii=False).replace(address,'TV')))
 return cleaned
def main():
 adb=shutil.which('adb')
 if not adb:raise RuntimeError('Chua co ADB; hay cai tool truoc.')
 files=list((ROOT/'logs').glob('auto-*.jsonl'))
 if not files:raise RuntimeError('Khong tim thay nhat ky cai tool.')
 log=max(files,key=lambda p:p.stat().st_mtime)
 rows=[]
 for line in log.read_text(encoding='utf-8-sig').splitlines():
  try:rows.append(json.loads(line))
  except ValueError:pass
 last=next((r['target'] for r in reversed(rows) if r.get('kind')=='adb' and r.get('target')),'')
 print('CHI DOC THONG TIN — khong cai, khong tat app, khong reboot.',flush=True)
 address=endpoint(input('IP TV ['+last+'] — Enter neu van dung: ').strip() or last)
 base=[adb,'-P',PORT]
 def run(args,target=True,timeout=20):
  try:
   p=subprocess.run(base+(['-s',address] if target else [])+args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',timeout=timeout)
   return {'code':p.returncode,'output':p.stdout.strip()}
  except subprocess.TimeoutExpired:return {'code':124,'output':'TIMEOUT'}
 for attempt in range(3):
  connection=run(['connect',address],False)
  state=run(['get-state'])
  if state['code']==0 and state['output']=='device':break
  print(connection['output']);print(state['output']);print('Bat ADB tren TV, cho phep ket noi neu TV hoi.',flush=True)
  if input('1 = thu lai | 0 = dung: ').strip()!='1':return 1
 else:raise RuntimeError('Chua ket noi duoc TV; chua doc chan doan.')
 data={}
 for name,args in READ_COMMANDS.items():
  print('Dang doc: '+name,flush=True)
  result=run(['shell']+args)
  if name=='activity':
   result['output']='\n'.join(s for s in result['output'].splitlines() if any(k in s for k in ('mResumedActivity','topResumedActivity',PACKAGE,'FallbackHome','com.mitv.tvhome')))[:20000]
  if name=='accessibility_runtime':
   result['output']='\n'.join(s for s in result['output'].splitlines() if any(k in s.lower() for k in ('user state','bound','binding','crashed','enabled services','projengmenu')))[:20000]
  data[name]=result
 paths=[s[8:] for s in data['projectivy_path']['output'].splitlines() if s.startswith('package:')]
 apk=next((p for p in paths if p.endswith('/base.apk')),paths[0] if paths else '')
 if apk and re.fullmatch(r'/[A-Za-z0-9_./+~=-]+',apk):data['installed_apk_sha256']=run(['shell','sha256sum',apk],timeout=30)
 for key in ('466.apk','mt9653.apk','project.apk'):
  f=ROOT/key
  if f.is_file():
   h=hashlib.sha256()
   with f.open('rb') as src:
    for block in iter(lambda:src.read(1024*1024),b''):h.update(block)
   data['bundled_'+key]={'code':0,'output':h.hexdigest()}
 report={'created':datetime.datetime.now().isoformat(),'source_log':log.name,'checks':data,'installation_log':redact(rows,address)}
 # A copy in the visible home directory can be shared manually if needed.
 output=pathlib.Path.home()/'xiaomi-home-report.json'
 output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print('\n=== KET QUA CAN CHUP ===')
 for k in ('model','firmware','hardware','board','soc','current_user','boot_completed','user_unlocked_property','home','home_default_only','home_with_default_category','projectivy_home'):
  print(k+': '+component(data[k]['output']))
 print('Tro nang: '+data['accessibility_services']['output'])
 print('SHA256 APK TV: '+data.get('installed_apk_sha256',{}).get('output','chua doc duoc'))
 print('Bao cao da luu: '+str(output))
 print('Hay chup phan KET QUA CAN CHUP gui vao chat. Chua reset/cai lai TV.')
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except (Exception,KeyboardInterrupt) as e:print('Da dung kiem tra: '+str(e));sys.exit(1)
