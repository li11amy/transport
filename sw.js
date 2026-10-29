// GitHub Pages is retired; production VPS still needs its original worker.
// Both environments share this source file, so never redirect VPS traffic.
const RETIRED_PAGES = self.location.hostname === "li11amy.github.io";
const NEW_HOME = "https://transport.peluche-ebanache.com/";
// Network-first schedule; cached timetable only when offline.
const CACHE="transport-bahia-v4", ROOT="/transport/";
const ASSETS=[ROOT,ROOT+"manifest.json",ROOT+"icon-180.png",ROOT+"icon-192-rgb.png",ROOT+"icon-512-rgb.png",ROOT+"icon-512-maskable.png"];
self.addEventListener("install",event=>{
  if (RETIRED_PAGES) {
    event.waitUntil(self.skipWaiting());
    return;
  }
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting()));
});
self.addEventListener("activate",event=>{
  event.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith("transport-bahia-")&&(RETIRED_PAGES||key!==CACHE)).map(key=>caches.delete(key)))),
    self.clients.claim()
  ]));
});
self.addEventListener("fetch",event=>{
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin||!url.pathname.startsWith(ROOT))return;
  if(RETIRED_PAGES){
    if(event.request.mode==="navigate"){
      // Migrate even older installed GitHub Pages PWAs, not just the page.
      event.respondWith(Response.redirect(NEW_HOME,302));
    }
    return;
  }
  if(url.pathname===ROOT+"transport_data.json") {
    event.respondWith((async()=>{
      const cache=await caches.open(CACHE);
      try {
        const response=await fetch(event.request,{cache:"no-store"});
        if(response.ok)await cache.put(event.request,response.clone());
        return response;
      } catch(error) {
        return (await cache.match(event.request))||Response.error();
      }
    })());
    return;
  }
  if(event.request.mode!=="navigate")return;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    try {
      const response=await fetch(event.request,{cache:"no-store"});
      if(response.ok)await cache.put(ROOT,response.clone());
      return response;
    }catch(error){
      return (await cache.match(ROOT))||Response.error();
    }
  })());
});
