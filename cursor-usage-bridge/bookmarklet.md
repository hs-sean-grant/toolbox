# Bookmarklet — one-shot sync

Use this when you don't want the extension, or to force an immediate sync while browsing cursor.com.

## How to install

1. Create a new bookmark in Chrome.
2. Name it **Sync Cursor Usage** (or similar).
3. Paste the minified URL below into the bookmark **URL** field.

## Minified bookmarklet

```
javascript:(async()=>{const I='http://127.0.0.1:8799/ingest';try{const g=u=>fetch(u,{credentials:'include'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});const usage=await g('https://cursor.com/api/usage');const summary=await g('https://cursor.com/api/usage-summary');let events=null;try{events=await fetch('https://cursor.com/api/dashboard/get-filtered-usage-events',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({pageSize:100,page:1})}).then(r=>r.json())}catch(e){}const res=await fetch(I,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({usage,summary,events})});const j=await res.json();alert(res.ok&&j.ok?'Usage synced to '+I:'Sync failed: '+(j.error||res.status))}catch(e){alert('Failed: '+e.message+' — are you on cursor.com and logged in?')}})();
```

Change `8799` in the URL if your dashboard runs on a different port.

## Readable source

Run **only while on https://cursor.com** (logged in). Requires the local dashboard (`server.py`) running with `/ingest`.

```javascript
(async () => {
  const INGEST = "http://127.0.0.1:8799/ingest";

  async function getJson(url, opts) {
    const res = await fetch(url, { credentials: "include", ...opts });
    if (!res.ok) throw new Error("HTTP " + res.status + " " + url);
    return res.json();
  }

  const usage = await getJson("https://cursor.com/api/usage");
  const summary = await getJson("https://cursor.com/api/usage-summary");

  let events = null;
  try {
    events = await getJson("https://cursor.com/api/dashboard/get-filtered-usage-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageSize: 100, page: 1 }),
    });
  } catch (e) {
    /* events optional */
  }

  const res = await fetch(INGEST, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ usage, summary, events }),
  });
  const data = await res.json();

  if (res.ok && data.ok) {
    alert("Usage synced to " + INGEST);
  } else {
    alert("Sync failed: " + (data.error || res.status));
  }
})();
```

## Extension vs bookmarklet

| | Extension | Bookmarklet |
|---|-----------|-------------|
| Install | Load unpacked once | Save bookmark once |
| Sync | Automatic (~10 min) + on install | Manual — click while on cursor.com |
| Best for | Daily dashboard | Quick one-off refresh |
