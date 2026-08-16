import json,urllib.request,time
UA={"User-Agent":"TraceTriage-recon/0.1 (kesavk659@gmail.com)"}
req=urllib.request.Request("https://network.satnogs.org/api/observations/?format=json&end=2026-07-15T00:00:00Z",headers=UA)
d=json.loads(urllib.request.urlopen(req,timeout=60).read())
got=0
for o in d:
    if o.get("waterfall") and o.get("waterfall_status")!="unknown":
        u=o["waterfall"]
        r=urllib.request.Request(u,headers=UA)
        with urllib.request.urlopen(r,timeout=90) as resp:
            b=resp.read(); ct=resp.headers.get("Content-Type")
        fn=f"wf_{o['id']}.png"
        open(fn,"wb").write(b)
        print(f"obs {o['id']} ws={o['waterfall_status']} client={o['client_version']} bytes={len(b)} ct={ct}")
        print("   url:",u[:120])
        got+=1
        if got>=3: break
        time.sleep(0.5)
