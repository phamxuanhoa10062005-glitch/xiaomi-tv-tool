#!/usr/bin/env python3
"""Replay the observed Windows-tool workflow with target-specific mobile ADB."""
import argparse, hashlib, ipaddress, json, pathlib, re, shutil, subprocess, sys, time

ROOT=pathlib.Path(__file__).resolve().parent
PORT='15039'
LOG=ROOT/'logs'/('auto-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')

def record(kind,**data):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open('a',encoding='utf-8') as f:
        f.write(json.dumps({'time':time.time(),'kind':kind,**data},ensure_ascii=False)+'\n')

def endpoint(text):
    parts=text.strip().split(':')
    if len(parts) not in (1,2):raise ValueError('Dùng IPv4:cổng của TV.')
    ip=ipaddress.IPv4Address(parts[0]);port=int(parts[1]) if len(parts)==2 else 5555
    if not 1<=port<=65535:raise ValueError('Cổng không hợp lệ.')
    return str(ip)+':'+str(port)

def load_plan(sdk):
    workflow=json.loads((ROOT/'workflow.json').read_text(encoding='utf-8'))
    variant=workflow['sdk_variants'].get(str(sdk))
    if not variant:raise ValueError('SDK '+str(sdk)+' chưa được đối chiếu với tool gốc. Dừng trước khi thay đổi TV.')
    steps=[[part.format(**variant) for part in row] for row in workflow['steps']]
    if len(steps)!=119:raise ValueError('Quy trình không đúng 119 bước đã ghi nhận.')
    return workflow,variant,steps

def preflight(steps):
    hashes=json.loads((ROOT/'payload-hashes.json').read_text())
    metadata=json.loads((ROOT/'apk-metadata.json').read_text(encoding='utf-8'))
    required=set()
    for args in steps:
        if args[0]=='install':required.add(args[-1])
        if args[0]=='push' and args[1]!='8.jpg':required.add(args[1])
    for name in sorted(required):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name not in hashes:
            raise ValueError('Tài nguyên không có trong danh mục: '+name)
        if name.endswith('.apk'):
            item=metadata.get(name,{})
            if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+',item.get('package','')) or not isinstance(item.get('versionCode'),int):
                raise ValueError('Thiếu thông tin gói APK hợp lệ: '+name)
        h=hashlib.sha256()
        with (ROOT/name).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        if h.hexdigest()!=hashes[name]:raise ValueError('Tài nguyên bị thay đổi: '+name)

def device_plan(info):
    sdk=int(info['ro.build.version.sdk'])
    workflow,variant,steps=load_plan(sdk)
    variant=dict(variant)
    astro=(sdk==30 and info.get('ro.product.model','').strip().upper() in ('MITV-ASTR0','MITV-ASTRO')
        and info.get('ro.board.platform','').strip().lower()=='blueplanet')
    if astro:
        variant['voice']='mitv11.apk'
        steps=[[part.format(**variant) for part in row] for row in workflow['steps']]
    return workflow,variant,steps,astro

def connect_with_retry(runner,address):
    """True=connected, False=enter another IP, None=exit. Keep the same target on retry."""
    target=endpoint(address)
    while True:
        try:
            print('Đang kết nối '+target+'...')
            runner.connect(target)
            print('Đã kết nối TV.')
            return True
        except (RuntimeError,subprocess.TimeoutExpired) as e:
            print('Chưa kết nối được: '+str(e))
            print('Trên TV, chọn Cho phép kết nối ADB rồi bấm 1 bên dưới.')
            while True:
                choice=input('1 = Thử lại cùng IP | 2 = Nhập IP khác | 0 = Thoát: ').strip()
                if choice=='1':break
                if choice=='2':return False
                if choice=='0':return None
                print('Chỉ nhập 1, 2 hoặc 0.')

def confirm_install():
    while True:
        choice=input('1 = Bắt đầu cài đặt | 0 = Thoát: ').strip()
        if choice=='1':return True
        if choice=='0':return False
        print('Chỉ nhập số 1 hoặc 0.')

def retain_newer_app(runner,filename):
    """Only keep a known optional app after confirming its installed version is higher."""
    metadata=json.loads((ROOT/'apk-metadata.json').read_text(encoding='utf-8'))
    item=metadata.get(filename)
    if not item or not item.get('keep_newer'):return None
    package=item['package']
    code,path=runner.call(['shell','pm','path','--user','0',package])
    if code or not re.search(r'^package:/',path,re.M):return None
    code,details=runner.call(['shell','dumpsys','package',package])
    match=re.search(r'\bversionCode=(\d+)\b',details)
    if code or not match:return None
    installed=int(match.group(1))
    if installed<=int(item['versionCode']):return None
    return {'file':filename,'package':package,'installedVersionCode':installed,
        'bundledVersionCode':int(item['versionCode'])}

def step_title(args):
    if args[0]=='install':return 'Cài ứng dụng '+args[-1]
    if args[0]=='push':return 'Chép tài nguyên '+args[1]
    if args[:3]==['shell','pm','disable-user']:return 'Thiết lập ứng dụng hệ thống: '+args[-1]
    if args[0]=='reboot':return 'Khởi động lại TV'
    if args[0]=='kill-server':return 'Kết thúc kết nối ADB của tool'
    if args[:2]==['shell','settings']:return 'Thiết lập TV: '+args[4] if len(args)>4 else 'Kiểm tra thiết lập TV'
    if args[:2]==['shell','appops'] or args[:3]==['shell','cmd','appops']:return 'Thiết lập quyền ứng dụng'
    if args[:2]==['shell','ime']:return 'Thiết lập bàn phím'
    return 'Thiết lập giao diện và chức năng TV'

class Runner:
    def __init__(self,adb):self.adb=adb;self.serial=''
    def call(self,args,target=True,timeout=300):
        if target and not self.serial:raise RuntimeError('Chưa có TV được chọn.')
        command=[self.adb,'-P',PORT]+(['-s',self.serial] if target else [])+list(args)
        p=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            encoding='utf-8',errors='replace',timeout=timeout)
        record('adb',args=args,target=self.serial if target else None,code=p.returncode,output=p.stdout)
        return p.returncode,p.stdout.strip()
    def checked(self,args,target=True,timeout=300):
        code,text=self.call(args,target,timeout=timeout)
        if code:raise RuntimeError(text or 'ADB không thực hiện được lệnh.')
        return text
    def connect(self,address):
        self.serial=''
        self.checked(['start-server'],False,timeout=15)
        self.checked(['connect',endpoint(address)],False,timeout=15)
        target=endpoint(address)
        code,state=self.call(['-s',target,'get-state'],False,timeout=8)
        if code or state!='device':raise RuntimeError('Chưa kết nối/ủy quyền TV. Chấp nhận khóa ADB trên TV rồi thử lại.')
        self.serial=target
    def info(self):
        props={}
        for key in ('ro.product.manufacturer','ro.product.model','ro.product.name','ro.serialno',
            'ro.build.display.id','ro.build.version.release','ro.build.version.sdk',
            'ro.soc.manufacturer','ro.soc.model','ro.hardware','ro.board.platform'):
            props[key]=self.checked(['shell','getprop',key])
        return props

def snapshot(runner,steps):
    code,disabled=runner.call(['shell','pm','list','packages','-d'])
    if code:raise RuntimeError('Không đọc được trạng thái ứng dụng; chưa thay đổi TV.')
    code,home=runner.call(['shell','cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.HOME'])
    settings={}
    for args in steps:
        if args[:3] in (['shell','settings','put'],['shell','settings','delete']):
            key=args[3]+':'+args[4]
            if key not in settings:
                rc,value=runner.call(['shell','settings','get',args[3],args[4]])
                if rc==0:settings[key]=value
    result={'serial':runner.serial,'disabled':[line[8:] for line in disabled.splitlines() if line.startswith('package:')],
        'home':home.splitlines()[-1] if home else '', 'settings':settings}
    record('snapshot',data=result)
    return result

def recovery(runner,before,touched):
    print('Đang thử khôi phục ứng dụng và thiết lập đã ghi nhận trước khi cài...')
    results=[]
    extra=[p for p in _home_disabled_by_fix if p not in touched]
    actions=[['shell','pm','enable','--user','0',p] for p in list(touched)+extra if p not in before['disabled']]
    if re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+',before['home']):
        actions.append(['shell','cmd','package','set-home-activity',before['home']])
    for key,value in before['settings'].items():
        scope,name=key.split(':',1)
        actions.append(['shell','settings','delete',scope,name] if value=='null' else ['shell','settings','put',scope,name,value])
    for args in actions:
        try:results.append(runner.call(args))
        except Exception as e:record('recovery_error',error=str(e))
    print('Đã thử khôi phục; đây không phải hoàn tác toàn bộ. APK đã cài, ảnh, appops và dữ liệu app có thể vẫn còn.')
    return results

LAUNCHER='com.spocky.projengmenu'
STOCK_HOME='com.mitv.tvhome'
_home_disabled_by_fix=[]

def _home_matches(text):
    return any(line.strip().split('/',1)[0]==LAUNCHER for line in text.splitlines())

def _resolved_home(runner,query):
    code,out=runner.call(query)
    if code:return None,out
    for line in out.splitlines():
        s=line.strip()
        if re.fullmatch(r'[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+',s):return s,out
    return None,out

def _package_disabled(runner,package):
    code,out=runner.call(['shell','pm','list','packages','-d','--user','0'])
    if code:raise RuntimeError('Không đọc được trạng thái gói; dừng trước khi tắt launcher: '+out)
    return any(line.strip()=='package:'+package for line in out.splitlines())

def _disable_package_verified(runner,package):
    """Disable a package for user 0 and confirm the state really changed.

    True only when the package is verified disabled afterwards. Packages this
    function disabled itself are remembered so recovery / a blocked reboot can
    re-enable exactly those (never packages that were already disabled)."""
    # FallbackHome belongs to Settings, not a competing launcher. Never disable
    # an arbitrary resolved package (Settings/System UI can also handle HOME).
    if package!=STOCK_HOME:return False
    if _package_disabled(runner,package):return True
    if package not in _home_disabled_by_fix:_home_disabled_by_fix.append(package)
    code,out=runner.call(['shell','pm','disable-user','--user','0',package])
    ok=_package_disabled(runner,package)
    record('disable_attempt',package=package,code=code,output=out,verified=ok)
    return ok

def require_launcher(runner,select=False,strict=True):
    query=['shell','cmd','package','resolve-activity','--brief','--user','0',
        '-a','android.intent.action.MAIN','-c','android.intent.category.HOME']
    code,out=runner.call(query+['-p',LAUNCHER])
    components=[s.strip() for s in out.splitlines() if re.fullmatch(r'com\.spocky\.projengmenu/[A-Za-z0-9_.$]+',s.strip())]
    if code or not components:raise RuntimeError('Không tìm được HOME Projectivy. Giữ giao diện Xiaomi; không khởi động lại.')
    component=components[-1]
    def verify():
        code,out=runner.call(query)
        return (not code) and _home_matches(out),out
    if select:
        code,out=runner.call(['shell','am','start','-W','-n',component])
        if code or not re.search(r'^Status:\s*ok\s*$',out,re.M) or re.search(r'Error|Exception|Failure',out,re.I):
            raise RuntimeError('Không mở được Projectivy: '+out)
        code,out=runner.call(['shell','cmd','package','set-home-activity','--user','0',component])
        if code or re.search(r'Error|Exception|Failure',out,re.I):raise RuntimeError('Không đặt được HOME: '+out)
        ok,out=verify()
        if not ok:
            # Android 10+ exposes the HOME role. OEMs may reject or omit this service.
            runner.call(['shell','cmd','role','add-role-holder','--user','0','android.app.role.HOME',LAUNCHER],timeout=30)
            ok,out=verify()
        if not ok:
            # Last resort: a stock launcher that stays enabled can hold HOME against
            # both set-home-activity and the HOME role (seen on Xiaomi firmware,
            # where the workflow's own disable step did not take). Disable the
            # competing stock home — reversible with pm enable — then set HOME again.
            rivals=[STOCK_HOME]
            current,_=_resolved_home(runner,query)
            if current and current.split('/',1)[0] not in (LAUNCHER,STOCK_HOME):
                record('protected_home_package',component=current)
            disabled_any=False
            for package in rivals:
                if _disable_package_verified(runner,package):disabled_any=True
            if disabled_any:
                runner.call(['shell','cmd','package','set-home-activity','--user','0',component])
                ok,out=verify()
                if not ok:
                    runner.call(['shell','cmd','role','add-role-holder','--user','0','android.app.role.HOME',LAUNCHER],timeout=30)
                    ok,out=verify()
    else:
        ok,out=verify()
    if not ok:
        record('home_unresolved',component=component,output=out)
        if strict:raise RuntimeError('HOME mặc định chưa trỏ tới Projectivy; dừng trước reboot.')
        return None
    record('launcher_verified',component=component)
    return component

def execute(runner,steps,verbose=False,original_order=False):
    _home_disabled_by_fix.clear()  # A previous run/TV must not affect recovery.
    preflight(steps)  # Complete all local checks before disabling anything on TV.
    before=snapshot(runner,steps)
    touched=[];warnings=[]
    try:
        # Install and validate HOME before any system app is disabled.
        launcher_step=next(row for row in steps if row[0]=='install' and row[-1] in ('466.apk','mt9653.apk'))
        if not original_order:
            code,out=runner.call(['install','-g',str(ROOT/launcher_step[-1])])
            if code or not re.search(r'^Success\s*$',out,re.M):raise RuntimeError('Cài launcher thất bại: '+out)
            require_launcher(runner,select=True,strict=False)
        for index,raw in enumerate(steps,1):
            args=list(raw)
            if not original_order and raw==launcher_step:continue
            if not original_order and raw[:3]==['shell','pm','disable-user'] and raw[-1]=='com.mitv.tvhome':
                record('stock_home_retained',package=raw[-1]);continue
            if not original_order and raw[:3]==['shell','am','start'] and LAUNCHER in ' '.join(raw):
                require_launcher(runner,select=True,strict=False);continue
            if not original_order and raw[:4]==['shell','cmd','package','set-home-activity']:
                require_launcher(runner,select=True,strict=False);continue
            if raw[0]=='reboot' and not require_launcher(runner,select=True,strict=False):
                # Complete app/resource setup but never reboot into an unresolved HOME.
                # Applies to every path (the strict original-order gate used to raise
                # here and roll back the whole run; the setup itself is not the failure).
                # Restore packages changed by either the workflow or the HOME
                # fallback, while preserving packages disabled before this run.
                for package in dict.fromkeys(touched+_home_disabled_by_fix):
                    if package not in before['disabled']:
                        rc,result=runner.call(['shell','pm','enable','--user','0',package])
                        record('blocked_reboot_restore',package=package,code=rc,output=result)
                _home_disabled_by_fix.clear()
                if re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+',before['home']) and not before['home'].startswith('android/'):
                    runner.call(['shell','cmd','package','set-home-activity','--user','0',before['home']])
                message='Đã chạy các bước cài app/tài nguyên, nhưng chưa xác nhận Projectivy làm HOME. Đã thử trả các gói vừa tắt về trạng thái trước cài; KHÔNG tự reboot. Chưa hoàn tất chuyển giao diện.'
                print(message);warnings.append(message);record('reboot_blocked',message=message)
                continue
            print('[%03d/%03d] %s' % (index,len(steps),' '.join(raw) if verbose else step_title(raw)))
            if args[:2]==['push','8.jpg']:
                message='8.jpg không có trong EXE gốc; bỏ qua đúng tài nguyên đang thiếu, không thay bằng ảnh khác.'
                warnings.append(message);record('missing_original',step=index,message=message)
                continue
            if args[0]=='install':args[-1]=str(ROOT/args[-1])
            elif args[0]=='push':args[1]=str(ROOT/args[1])
            target=args[0] not in ('kill-server','start-server','devices','connect')
            code,out=runner.call(args,target)
            if args[0]=='install' and (code or not re.search(r'^Success\s*$',out,re.M)):
                if re.search(r'\bINSTALL_FAILED_VERSION_DOWNGRADE\b',out):
                    retained=retain_newer_app(runner,raw[-1])
                    if retained:
                        message=raw[-1]+': giữ bản mới hơn trên TV ('+str(retained['installedVersionCode'])+' > '+str(retained['bundledVersionCode'])+'), tiếp tục cài các mục còn lại.'
                        print(message);warnings.append(message)
                        record('kept_newer_app',step=index,**retained)
                        continue
                raise RuntimeError('Cài APK thất bại: '+raw[-1]+' — '+out)
            if code and re.search(r'device .*not found|device offline|no devices/emulators|transport error|connection closed',out,re.I):
                raise RuntimeError('Mất kết nối TV: '+out)
            failed=code or re.search(r'\bError\b|\bFailure\b|Unknown operation|Permission denial|Exception occurred',out,re.I)
            if failed:
                warnings.append('Bước '+str(index)+': '+out);record('step_warning',step=index,output=out)
            if raw[:3]==['shell','pm','disable-user'] and not failed:touched.append(raw[-1])
    except (Exception,KeyboardInterrupt):
        recovery(runner,before,touched)
        raise
    record('finished',warnings=warnings)
    print('\nĐã kết thúc lượt cài; xem cảnh báo để biết trạng thái chuyển HOME/reboot.')
    print('Có %s cảnh báo; xem nhật ký: %s' % (len(warnings),LOG))
    print('Kiểm tra giao diện, bàn phím, giọng nói và remote trực tiếp trên TV. Gửi xong lệnh chưa chứng minh mọi chức năng hoạt động.')
    return warnings

def main():
    parser=argparse.ArgumentParser(description='Cài tự động theo quy trình đã ghi từ tool Windows')
    parser.add_argument('--preview',action='store_true',help='Chỉ đọc thông tin TV và hiển thị quy trình, không cài')
    parser.add_argument('--verbose',action='store_true',help='Hiển thị đầy đủ từng lệnh; mặc định dùng thông báo ngắn')
    args=parser.parse_args()
    adb=shutil.which('adb')
    if not adb:raise RuntimeError('Thiếu ADB. Hãy chạy bằng start.sh trong Termux/iSH.')
    runner=Runner(adb)
    print('\n=== XIAOMI AUTO SETUP — BẢN ĐIỆN THOẠI 2.5.1-fix1-reviewed ===')
    print('Đã đối chiếu lệnh với tool Windows; chưa xác minh hoàn tất trên mọi TV thật.')
    while True:
        address=input('Nhập IP:cổng TV | 3 = Ghép đôi ADB | 0 = Thoát: ').strip()
        if address=='0':return
        if address in ('3','pair'):
            pairing=endpoint(input('IP:cổng GHÉP ĐÔI hiển thị trên TV: '))
            code=input('Mã ghép đôi 6 số: ').strip()
            if not re.fullmatch(r'\d{6}',code):raise ValueError('Mã phải gồm 6 chữ số.')
            # Do not include pairing secrets in the regular command log.
            result=subprocess.run([adb,'-P',PORT,'pair',pairing,code])
            if result.returncode:print('Ghép đôi thất bại; kiểm tra bản ADB và TV.')
            print('Sau đó dùng cổng KẾT NỐI, khác cổng ghép đôi.')
            continue
        try:connected=connect_with_retry(runner,address)
        except ValueError as e:
            print('IP chưa hợp lệ: '+str(e));continue
        if connected is None:return
        if connected:break
    info=runner.info()
    for key,title in (('ro.product.manufacturer','Hãng'),('ro.product.model','Model'),
        ('ro.build.display.id','Firmware'),('ro.build.version.release','Android'),
        ('ro.build.version.sdk','SDK'),('ro.board.platform','Nền tảng')):
        print(title+': '+info[key])
    if info['ro.product.manufacturer'].lower() not in ('xiaomi','redmi'):
        raise ValueError('Thiết bị chưa nhận dạng là Xiaomi/Redmi; dừng trước khi thay đổi.')
    workflow,variant,steps,astro=device_plan(info)
    preflight(steps)
    print('Launcher: '+variant['launcher']+' | Giọng nói: '+variant['voice'])
    if astro:print('ĐÃ NHẬN DẠNG ASTR0/ASTRO — blueplanet SDK 30: mitv11.apk, thứ tự cài EXE gốc.')
    if args.preview:
        for i,row in enumerate(steps,1):print('%03d %s'%(i,' '.join(row)))
        print('Chỉ xem quy trình; chưa thay đổi TV.');return
    print('\nQuy trình sẽ thay launcher, vô hiệu hóa một số ứng dụng/cập nhật Xiaomi,')
    print('đổi ngôn ngữ/múi giờ, cài APK, chép ảnh/cấu hình, đặt bàn phím/trợ năng và khởi động lại TV.')
    print('8.jpg không có trong file gốc nên sẽ được báo thiếu và bỏ qua.')
    if not confirm_install():return
    execute(runner,steps,verbose=args.verbose,original_order=astro)

def cli():
    status=0
    try:main()
    except (Exception,KeyboardInterrupt) as e:
        record('stopped',error=str(e));print('\nĐã dừng: '+str(e),file=sys.stderr);status=1
    finally:
        if sys.stdin.isatty():
            try:input('\nNhấn Enter để thoát tool: ')
            except (EOFError,KeyboardInterrupt):pass
    return status

if __name__=='__main__':sys.exit(cli())
