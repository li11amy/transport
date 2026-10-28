"""Read-only checks of published PWA assets and official maritime status site."""
import re
import requests
from bs4 import BeautifulSoup

SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0 Chrome/130.0.0.0"})
for base in ["https://peluche-ebanache.com/transport/","https://cmtbc.es/?op=maritimo"]:
    print("\n=== URL",base,"===",flush=True)
    try:
        response=SESSION.get(base,timeout=20)
        print("STATUS",response.status_code,"final",response.url,"MIME",response.headers.get("Content-Type"),"BYTES",len(response.content))
        print("HTML HEAD",response.text[:450].replace("\n"," "))
        soup=BeautifulSoup(response.text,"html.parser")
        for script in soup.find_all("script"):
            if script.has_attr("src"):
                print("SCRIPT URL",script["src"])
            elif "maritimo" in script.text.lower() or "estado" in script.text.lower() or "fetch(" in script.text:
                print("INLINE SCRIPT",script.text[:2500])
        for tag in soup.select("[id*='marit'],[class*='marit'],[id*='estado'],[class*='estado']"):
            print("SERVICE ELEMENT",str(tag)[:700])
    except Exception as exc:
        print("ERROR",str(exc))
for name in ["manifest.json","sw.js","icon-192.png","icon-512.png","icon-180.png","transport_data.json"]:
    url="https://peluche-ebanache.com/transport/"+name
    try:
        r=SESSION.get(url,timeout=15)
        print("RESOURCE",name,"code",r.status_code,"content-type",r.headers.get("Content-Type"),"length",len(r.content),"redirect",r.url,"start",repr(r.content[:30]))
        if name=="manifest.json" and r.ok:
            print("MANIFEST",r.text[:1800])
        if name.endswith(".png") and r.ok and r.content[:8]==b"\x89PNG\r\n\x1a\n":
            print("PNG dimensions",int.from_bytes(r.content[16:20],"big"),int.from_bytes(r.content[20:24],"big"),"color_type",r.content[25])
    except Exception as exc:
        print("RESOURCE ERROR",name,str(exc))
