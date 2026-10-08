// Sessions without a database: the GitHub token lives in an encrypted, HttpOnly cookie.
// AES-256-GCM with a key derived from SESSION_SECRET (set it in Vercel's environment settings).

const COOKIE = "skylls_session";
const STATE_COOKIE = "skylls_oauth_state";
const MAX_AGE = 30 * 86400; // seconds: stay signed in for 30 days (GitHub tokens are renewed as needed)

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

function fromB64url(text) {
  return new Uint8Array(Buffer.from(text, "base64url"));
}

async function key() {
  const secret = process.env.SESSION_SECRET || "";
  if (secret.length < 32) throw new Error("SESSION_SECRET must be set (at least 32 characters)");
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(secret));
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function seal(data) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const body = enc.encode(JSON.stringify({ ...data, exp: Math.floor(Date.now() / 1000) + MAX_AGE }));
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(), body));
  return b64url(iv) + "." + b64url(sealed);
}

export async function unseal(value) {
  try {
    const [iv, sealed] = value.split(".");
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromB64url(iv) }, await key(), fromB64url(sealed));
    const data = JSON.parse(dec.decode(plain));
    return data.exp > Date.now() / 1000 ? data : null;
  } catch {
    return null;
  }
}

export function cookies(request) {
  const out = {};
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function cookieHeader(name, value, request, maxAge) {
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `${name}=${encodeURIComponent(value)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure}`;
}

export async function sessionCookie(request, data) {
  return cookieHeader(COOKIE, await seal(data), request, MAX_AGE);
}

export function clearSessionCookie(request) {
  return cookieHeader(COOKIE, "", request, 0);
}

export function stateCookie(request, state) {
  return cookieHeader(STATE_COOKIE, state, request, 600);
}

export function clearStateCookie(request) {
  return cookieHeader(STATE_COOKIE, "", request, 0);
}

export function readState(request) {
  return cookies(request)[STATE_COOKIE] || "";
}

/** The signed-in user ({token, login}) or null. */
export async function getSession(request) {
  const value = cookies(request)[COOKIE];
  return value ? unseal(value) : null;
}
