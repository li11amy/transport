// Network-first schedule; cached timetable only when offline.
const CACHE="transport-bahia-v3", ROOT="/transport/";
const ASSETS=[ROOT,ROOT+"manifest.json",ROOT+"icon-180.png",ROOT+"icon-192.png",ROOT+"icon-512.png"];
self.addEventListener("install",event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting()));
});
self.addEventListener("activate",event=>{
  event.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith("transport-bahia-")&&key!==CACHE).map(key=>caches.delete(key)))),
    self.clients.claim()
  ]));
});
self.addEventListener("fetch",event=>{
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin||!url.pathname.startsWith(ROOT))return;
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
