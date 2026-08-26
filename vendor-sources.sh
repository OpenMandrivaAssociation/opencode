#!/bin/bash
# Produce OpenCode's offline sources. Requires a working `bun`.
#
# Rule: no prebuilt binaries. bun install is JS-only (--ignore-scripts).
# Do not use --os=linux --cpu=* to pull npm optional native packages
# (@opentui/core-linux-*, @ff-labs/fff-bin-*). Those .so files are
# prebuilts. %build compiles libopentui.so (Zig) and libfff_c.so
# (Rust) from source and stages the JS wrappers bun --compile needs.
set -euo pipefail

VERSION="${1:-1.18.22}"
HERE=$(cd "$(dirname "$0")" && pwd)
WORKDIR=$(mktemp -d -p "${TMPDIR:-$HERE}")
export TMPDIR="$WORKDIR"
trap 'rm -rf "$WORKDIR"' EXIT

TGZ="$HERE/opencode-${VERSION}.tar.gz"
if [ ! -f "$TGZ" ]; then
	curl -fL -o "$TGZ" \
		"https://github.com/anomalyco/opencode/archive/v${VERSION}/opencode-${VERSION}.tar.gz"
fi

tar -xf "$TGZ" -C "$WORKDIR"
SRC="$WORKDIR/opencode-${VERSION}"

echo "==> bun install --ignore-scripts (JS only, host platform)"
(
	cd "$SRC"
	export HOME="$WORKDIR/home"
	mkdir -p "$HOME"
	bun install --frozen-lockfile --ignore-scripts --no-progress \
		--filter opencode \
		--filter '@opencode-ai/core' \
		--filter '@opencode-ai/script' \
		--filter '@opencode-ai/sdk' \
		--filter '@opencode-ai/plugin' \
		--filter '@opencode-ai/protocol' \
		--filter '@opencode-ai/schema' \
		--filter '@opencode-ai/server' \
		--filter '@opencode-ai/tui' \
		--filter '@opencode-ai/llm' \
		--filter '@opencode-ai/codemode' \
		--filter '@opencode-ai/http-recorder' \
		--filter '@opencode-ai/app' \
		--filter '@opencode-ai/ui' \
		--filter '@opencode-ai/session-ui'

	# JS wrappers only — never pack ELF/PE/Mach-O natives or npm tool binaries.
	find . -type f \( \
		-name '*.so' -o -name '*.node' -o -name '*.dll' -o -name '*.dylib' -o \
		-name '*.exe' -o -name '*.a' -o -name '*.bare' -o \
		-name 'esbuild' -o -name 'turbo' -o -name 'oxlint' \
		\) -delete
	find . -type f \( -name 'sst' -o -name 'rollup' -o -name 'lightningcss' \) -delete
	# Catch natives that do not use a conventional extension (xsel, tsgo, …).
	find . -type f ! -name '*.js' ! -name '*.ts' ! -name '*.json' ! -name '*.md' \
		! -name '*.map' ! -name '*.wasm' -print0 |
		xargs -0 -r file -N |
		awk -F': ' '$2 ~ /^(ELF|PE32|Mach-O|MS-DOS)/ { print $1 }' |
		xargs -r rm -f
	# Drop leftover optional platform packages entirely; %build recreates
	# the host-arch wrappers next to the from-source .so.
	find . -type d \( \
		-name 'core-linux-*' -o \
		-name 'core-darwin-*' -o \
		-name 'core-win32-*' -o \
		-name 'fff-bin-*' \
		\) -prune -exec rm -rf {} +

	tar -cJf "$HERE/opencode-${VERSION}-node_modules.tar.xz" \
		node_modules \
		packages/*/node_modules \
		packages/*/*/node_modules \
		2>/dev/null || \
	tar -cJf "$HERE/opencode-${VERSION}-node_modules.tar.xz" node_modules
)

echo "==> Vite natives from source (rollup / lightningcss / oxide / esbuild)"
# No npm .node, no WASM. %build compiles these against the host libc.
NAT="$WORKDIR/vite-natives"
mkdir -p "$NAT"
(
	cd "$WORKDIR"
	curl -fL -o rollup.tgz \
		https://github.com/rollup/rollup/archive/v4.60.4/rollup-4.60.4.tar.gz
	curl -fL -o lightningcss.tgz \
		https://github.com/parcel-bundler/lightningcss/archive/refs/tags/v1.30.1.tar.gz
	curl -fL -o tailwind.tgz \
		https://github.com/tailwindlabs/tailwindcss/archive/refs/tags/v4.1.11.tar.gz
	curl -fL -o esbuild.tgz \
		https://github.com/evanw/esbuild/archive/v0.25.12/esbuild-0.25.12.tar.gz
	tar -xzf rollup.tgz -C "$NAT"
	tar -xzf lightningcss.tgz -C "$NAT"
	tar -xzf tailwind.tgz -C "$NAT"
	tar -xzf esbuild.tgz -C "$NAT"

	# Nightly rustflags break cooker rustc; drop them.
	rm -f "$NAT/rollup-4.60.4/rust/bindings_napi/.cargo/config.toml"
	find "$NAT" -maxdepth 3 \( -name rust-toolchain -o -name rust-toolchain.toml \) -delete

	( cd "$NAT/rollup-4.60.4/rust" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/lightningcss-1.30.1" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/tailwindcss-4.1.11" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/esbuild-0.25.12" && go mod vendor )

	# Do not ship Windows import libs / DLLs. Stub napi-build
	# include_bytes so Linux cargo still compiles windows.rs.
	find "$NAT" -type f \( -name '*.a' -o -name '*.lib' -o -name '*.dll' \
		-o -name '*.so' -o -name '*.node' -o -name '*.wasm' \) -delete
	NAT="$NAT" python - <<'PY'
import hashlib, json, os
from pathlib import Path
root = Path(os.environ["NAT"])
for win in list(root.rglob("napi-build/src/windows.rs")) + list(root.rglob("napi-build-*/src/windows.rs")):
	text = win.read_text()
	if "include_bytes!" not in text:
		continue
	for name in ("node-x64.lib", "node-x86.lib", "node-arm64.lib"):
		text = text.replace(f'include_bytes!("libs/{name}").to_vec()', "Vec::new()")
	win.write_text(text)
	csum = win.parents[1] / ".cargo-checksum.json"
	if not csum.is_file():
		continue
	data = json.loads(csum.read_text())
	data["files"]["src/windows.rs"] = hashlib.sha256(win.read_bytes()).hexdigest()
	for k in list(data.get("files", {})):
		p = win.parents[1] / k
		if not p.exists():
			del data["files"][k]
	csum.write_text(json.dumps(data, separators=(",", ":")))
# Drop checksum entries for deleted binaries.
for csum in root.rglob(".cargo-checksum.json"):
	data = json.loads(csum.read_text())
	changed = False
	for k in list(data.get("files", {})):
		if not (csum.parent / k).exists():
			del data["files"][k]
			changed = True
	if changed:
		csum.write_text(json.dumps(data, separators=(",", ":")))
PY

	rm -rf "$NAT/rollup-4.60.4/"{docs,examples,test,src,cli,browser,wasm,.github} \
		"$NAT/lightningcss-1.30.1/"{website,.github} \
		"$NAT/tailwindcss-4.1.11/"{packages,playgrounds,integrations,.github} \
		"$NAT/esbuild-0.25.12/"{npm,lib,.github}
)
tar -C "$WORKDIR" -cJf "$HERE/opencode-vite-natives.tar.xz" vite-natives

echo "==> models.dev API snapshot"
curl -fL -o "$HERE/models-dev-api.json" "https://models.dev/api.json"

echo
echo "Store these with abb store:"
echo "  $TGZ"
echo "  $HERE/opencode-${VERSION}-node_modules.tar.xz"
echo "  $HERE/models-dev-api.json"
echo "  $HERE/opentui-zig-0.4.5.tar.xz"
echo "  $HERE/fff-0.9.4-with-vendor.tar.xz"
echo "  $HERE/opencode-vite-natives.tar.xz"
