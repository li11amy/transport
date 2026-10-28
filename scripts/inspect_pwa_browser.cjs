// Read-only Chrome installability audit for a public transport PWA.
const puppeteer = require('puppeteer-core');
(async()=>{
  const chrome = process.env.CHROME_BIN || '/usr/bin/google-chrome';
  const browser = await puppeteer.launch({
    executablePath: chrome,
    headless: true,
    args: ['--no-sandbox','--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    page.on('console', m=>console.log('CONSOLE',m.type(),m.text().slice(0,350)));
    page.on('pageerror',e=>console.log('PAGEERROR',String(e)));
    const response=await page.goto('https://peluche-ebanache.com/transport/',{waitUntil:'networkidle2',timeout:45000});
    console.log('PAGE',response?.status(),page.url());
    const cdp=await page.createCDPSession();
    for(const command of ['Page.getAppManifest','Page.getInstallabilityErrors']){
      try{
        const result=await cdp.send(command);
        console.log(command,JSON.stringify(result).slice(0,5000));
      }catch(e){console.log('ERROR',command,String(e))}
    }
    console.log('SERVICEWORKER',await page.evaluate(async()=>{
      const r={supported:'serviceWorker' in navigator,controlled:!!navigator.serviceWorker.controller};
      if(r.supported){
        try{const regs=await navigator.serviceWorker.getRegistrations();
          r.registrations=regs.map(x=>({scope:x.scope,active:x.active?.state,installing:x.installing?.state}))}
        catch(e){r.error=String(e)}
      }
      return r;
    }));
  } finally {await browser.close()}
})().catch(err=>{console.error(err);process.exitCode=1});
