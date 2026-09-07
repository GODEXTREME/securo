/**
 * The bookmarklet's source, built for one token.
 *
 * It runs on the state portal's page, where the person's browser has
 * already passed whatever that portal asks — a Cloudflare challenge in
 * Espírito Santo, an F5 script in Rio de Janeiro. Nothing here defeats
 * any of that; it reads a page that is already on screen.
 *
 * Constraints that shape the code:
 *   - It is one URI, so it must be a single expression with no newlines.
 *   - `text/plain` keeps it a "simple request", so the browser sends it
 *     without a preflight the portal's page would have to survive.
 *   - Only single quotes, so the whole thing can sit in an href or a
 *     bookmark field without escaping.
 */
export function buildBookmarklet(origin: string, secret: string): string {
  const endpoint = `${origin.replace(/\/$/, '')}/api/receipt-capture`
  const source = [
    'javascript:(function(){',
    'try{',
    `var u='${endpoint}',t='${secret}';`,
    "var h=document.documentElement.outerHTML;",
    "fetch(u,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({token:t,html:h})})",
    ".then(function(r){return r.json().catch(function(){return{}}).then(function(j){",
    "alert(r.ok?'Securo: nota importada.':'Securo: '+((j.detail&&j.detail.code)||r.status))})})",
    ".catch(function(e){alert('Securo: falhou ('+e+')')});",
    "}catch(e){alert('Securo: '+e)}",
    '})()',
  ].join('')
  return source
}
