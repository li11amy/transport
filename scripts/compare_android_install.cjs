const puppeteer=require("puppeteer-core");
const urls=["https://peluche-ebanache.com/transport/","https://design.bb.peluche-ebanache.com/"];
(async()=>{
 const browser=await puppeteer.launch({executablePath:"/usr/bin/google-chrome",headless:true,args:["--no-sandbox","--disable-dev-shm-usage"]});
 try{
  for(const url of urls){
   const page=await browser.newPage();
   await page.setViewport({width:390,height:844,isMobile:true,deviceScaleFactor:2,hasTouch:true});
   page.on("pageerror",e=>console.log("ERROR JS",url,String(e)));
   let response;
   try{response=await page.goto(url,{waitUntil:"networkidle2",timeout:45000});}
   catch(e){console.log("NAV ERROR",url,String(e));continue;}
   console.log("URL",url,"status",response.status(),"final",page.url());
   const basics=await page.evaluate(async()=>({
    location:location.href,
    links:[...document.querySelectorAll('link[rel]')].filter(n=>/manifest|icon/.test(n.rel)).map(n=>({rel:n.rel,href:n.href,sizes:n.sizes?.value,type:n.type})),
    head:[...document.querySelectorAll('meta[name]')].filter(n=>/theme-color|mobile-web-app|application-name/.test(n.name)).map(n=>({name:n.name,content:n.content})),
    standalone:matchMedia('(display-mode: standalone)').matches,
    sw: ('serviceWorker' in navigator)?(await navigator.serviceWorker.getRegistrations()).map(x=>({scope:x.scope,active:x.active?.state})):[],
   }));
   console.log("BASICS",JSON.stringify(basics));
   const client=await page.createCDPSession();
   for(const src of basics.links.filter(x=>/icon/.test(x.rel)).map(x=>x.href)){
    try{
      const r=await fetch(src);
      const buffer=Buffer.from(await r.arrayBuffer());
      console.log("LINK ICON",src,"status",r.status,"size",buffer.length,
       "type",buffer[25],"width",buffer.readUInt32BE(16),"height",buffer.readUInt32BE(20),
       "contentType",r.headers.get("content-type"));
    }catch(e){console.log("LINK ICON ERROR",src,String(e))}
   }
   for(const op of ["Page.getAppManifest","Page.getInstallabilityErrors"]){
    try{const x=await client.send(op);console.log(op,JSON.stringify(x).slice(0,4500))}
    catch(e){console.log("CDP ERROR",op,String(e))}
   }
   const manifest=await client.send("Page.getAppManifest");
   const declared=(manifest.manifest?.icons||[]).map(x=>x.url);
   for(const src of [...new Set(declared)]){
    try{
      const r=await fetch(src);const buffer=Buffer.from(await r.arrayBuffer());
      console.log("MANIFEST ICON",src,"status",r.status,"size",buffer.length,
       "type",buffer[25],"width",buffer.readUInt32BE(16),"height",buffer.readUInt32BE(20),
       "contentType",r.headers.get("content-type"));
    }catch(e){console.log("MANIFEST ICON ERROR",src,String(e))}
   }
   await page.close();
  }
 }finally{await browser.close()}
})().catch(e=>{console.log("FATAL",String(e));process.exitCode=1});
