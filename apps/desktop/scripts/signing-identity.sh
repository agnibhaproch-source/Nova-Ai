#!/usr/bin/env bash
# Creates a stable local code-signing identity for Nova's macOS builds (once per machine).
# macOS remembers Screen Recording permission per signing identity; ad-hoc builds get a new
# identity every build, so macOS asks again. Everything lives in apps/desktop/.signing (gitignored).
# A Developer ID certificate (CSC_LINK / CSC_NAME) replaces this for public releases.
set -euo pipefail
D="$(cd "$(dirname "$0")/.." && pwd)/.signing"
KC="$D/nova-signing.keychain-db"
[ -f "$KC" ] && { echo "signing identity already exists: $KC"; exit 0; }
mkdir -p "$D" && chmod 700 "$D" && cd "$D"
cat > cert.cnf <<'CNF'
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=Nova Local Signing
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
CNF
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config cert.cnf -keyout key.pem -out cert.pem 2>/dev/null
P12_PW=$(openssl rand -hex 16)
openssl pkcs12 -export -legacy -inkey key.pem -in cert.pem -out nova-signing.p12 -passout "pass:$P12_PW" 2>/dev/null \
  || openssl pkcs12 -export -inkey key.pem -in cert.pem -out nova-signing.p12 -passout "pass:$P12_PW"
KC_PW=$(openssl rand -hex 16)
printf %s "$KC_PW" > keychain.pass && chmod 600 keychain.pass
security create-keychain -p "$KC_PW" "$KC"
security set-keychain-settings "$KC"
security unlock-keychain -p "$KC_PW" "$KC"
security import nova-signing.p12 -k "$KC" -P "$P12_PW" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple: -s -k "$KC_PW" "$KC" >/dev/null
rm -f key.pem cert.cnf nova-signing.p12
echo "created signing identity in $KC"
