#!/bin/bash
# Produce OpenCode's offline sources. Requires a working `bun`, cargo, and git.
#
# Rule: no prebuilt binaries. bun install is JS-only (--ignore-scripts,
# --omit=optional). Do not pull npm optional native packages
# (@opentui/core-linux-*, @ff-labs/fff-bin-*, @rolldown/binding-*, …).
# Those .so/.node files are prebuilts. %build compiles libopentui.so (Zig),
# libfff_c.so (Rust), opencode-pty (Rust, system libghostty-vt), the
# rolldown/lightningcss/oxide natives, and @parcel/watcher from source.
#
# fff 0.10.5 and OpenTUI 0.8.1 (Zig 0.17, zig-deps vendored) are packed
# separately (fff-0.10.5-with-vendor.tar.xz, opentui-zig-0.8.1.tar.xz).
# This script does not regenerate them.
#
# Put TMPDIR on a real disk. /tmp is often a small tmpfs, and node_modules
# plus the Rolldown vendor tree do not fit there.
set -euo pipefail

VERSION="${1:-2.2.6}"
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
	# cli is the TUI binary. app is the embedded web UI. Workspace
	# dependencies come along. Optional deps are the prebuilt natives.
	bun install --frozen-lockfile --ignore-scripts --omit=optional --no-progress \
		--filter '@opencode/cli' \
		--filter '@opencode/app'

	# JS wrappers only — never pack ELF/PE/Mach-O natives or npm tool binaries.
	find . -type f \( \
		-name '*.so' -o -name '*.node' -o -name '*.dll' -o -name '*.dylib' -o \
		-name '*.exe' -o -name '*.a' -o -name '*.bare' -o \
		-name 'esbuild' -o -name 'turbo' -o -name 'oxlint' \
		\) -delete
	find . -type f \( -name 'sst' -o -name 'rollup' -o -name 'lightningcss' -o -name 'rolldown' \) -delete
	# Catch natives that do not use a conventional extension (xsel, tsgo, …).
	find . -type f ! -name '*.js' ! -name '*.ts' ! -name '*.json' ! -name '*.md' \
		! -name '*.map' ! -name '*.wasm' -print0 |
		xargs -0 -r file -N |
		awk -F': ' '$2 ~ /^(ELF|PE32|Mach-O|MS-DOS)/ { print $1 }' |
		xargs -r rm -f
	# Drop leftover platform packages; %build recreates the host one
	# next to the library it just compiled.
	find . -type d \( \
		-name 'core-linux-*' -o \
		-name 'core-darwin-*' -o \
		-name 'core-win32-*' -o \
		-name 'fff-bin-*' -o \
		-name 'watcher-linux-*' -o \
		-name 'watcher-darwin-*' -o \
		-name 'watcher-win32-*' -o \
		-name 'pty-linux-*' -o \
		-name 'pty-darwin-*' -o \
		-name 'pty-win32-*' -o \
		-name 'node-pty-*' -o \
		-name 'ffi-rs-*' -o \
		-name 'binding-linux-*' -o \
		-name 'binding-darwin-*' -o \
		-name 'binding-win32-*' -o \
		-name 'binding-android-*' -o \
		-name 'binding-freebsd-*' -o \
		-name 'oxide-linux-*' -o \
		-name 'oxide-darwin-*' -o \
		-name 'oxide-win32-*' -o \
		-name 'rollup-linux-*' -o \
		-name 'rollup-darwin-*' -o \
		-name 'rollup-win32-*' \
		\) -prune -exec rm -rf {} +

	# Isolated installs keep real modules under node_modules/.bun and
	# only symlinks under packages/*/node_modules. An unmatched glob
	# must not drop those symlinks: bun cannot resolve @opentui/core
	# from packages/cli without them.
	shopt -s nullglob
	paths=(node_modules packages/*/node_modules packages/*/*/node_modules)
	tar -cf - "${paths[@]}" | xz -T0 -c > "$HERE/opencode-${VERSION}-node_modules.tar.xz"
)

echo "==> models.dev catalog snapshot"
# Same trim and validation the release build uses. The URL is
# https://models.opencode.ai/experimental/v2.0/api.json?type=chat,decision,image
(
	cd "$SRC/packages/core"
	bun ./script/update-models-snapshot.ts "$HERE/models-dev-api.json"
)

echo "==> Vite natives from source (rolldown / rollup / lightningcss / oxide)"
# No npm .node, no WASM fallback. %build compiles these against the host libc.
# Vite 8 bundles the web UI with Rolldown. vite-plugin-pwa's workbox-build
# still loads Rollup 4.62. Tailwind 4.3.3 loads lightningcss 1.32.0
# (@tailwindcss/node) and Vite itself loads 1.33.0.
NAT="$WORKDIR/vite-natives"
mkdir -p "$NAT"
(
	cd "$WORKDIR"
	git clone --depth 1 --branch v1.2.5 https://github.com/rolldown/rolldown.git "$NAT/rolldown-1.2.5"
	curl -fL -o rollup.tgz \
		https://github.com/rollup/rollup/archive/v4.62.4/rollup-4.62.4.tar.gz
	curl -fL -o lightningcss.tgz \
		https://github.com/parcel-bundler/lightningcss/archive/refs/tags/v1.33.0.tar.gz
	curl -fL -o lightningcss132.tgz \
		https://github.com/parcel-bundler/lightningcss/archive/refs/tags/v1.32.0.tar.gz
	curl -fL -o tailwind.tgz \
		https://github.com/tailwindlabs/tailwindcss/archive/refs/tags/v4.3.3.tar.gz
	tar -xzf rollup.tgz -C "$NAT"
	tar -xzf lightningcss.tgz -C "$NAT"
	tar -xzf lightningcss132.tgz -C "$NAT"
	tar -xzf tailwind.tgz -C "$NAT"

	# Nightly/pinned rustflags break cooker rustc; drop them.
	find "$NAT" \( -name rust-toolchain -o -name rust-toolchain.toml \) -delete
	rm -f "$NAT/rollup-4.62.4/rust/bindings_napi/.cargo/config.toml" \
		"$NAT/rollup-4.62.4/rust/bindings_wasm/.cargo/config.toml"
	rm -rf "$NAT/rolldown-1.2.5/.git"

	( cd "$NAT/rolldown-1.2.5" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/lightningcss-1.33.0" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/lightningcss-1.32.0" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/tailwindcss-4.3.3" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )
	( cd "$NAT/rollup-4.62.4/rust" && mkdir -p .cargo && \
		cargo vendor --locked cargo-vendor > .cargo/config.toml )

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

	rm -rf "$NAT/rolldown-1.2.5/"{docs,examples,.github} \
		"$NAT/rollup-4.62.4/"{docs,examples,test,src,cli,browser,wasm,.github} \
		"$NAT/lightningcss-1.33.0/"{website,.github} \
		"$NAT/lightningcss-1.32.0/"{website,.github} \
		"$NAT/tailwindcss-4.3.3/"{playgrounds,integrations,.github}
)
tar -C "$WORKDIR" -cJf "$HERE/opencode-vite-natives.tar.xz" vite-natives

# opencode-pty links system libghostty-vt. Vendor the Rust crates only.
# Do not fetch Ghostty; Patch0 replaces build.rs.
echo "==> cargo vendor opencode-pty"
(
	cd "$SRC/packages/process-daemon"
	rm -rf cargo-vendor .cargo
	rm -f rust-toolchain.toml
	mkdir -p .cargo
	# cargo prints the source replacement and does not write it.
	cargo vendor --locked cargo-vendor > .cargo/config.toml
)
tar -C "$SRC/packages/process-daemon" -cJf "$HERE/opencode-pty-vendor.tar.xz" .cargo cargo-vendor

echo
echo "Store these with abb store (remove replaced keys from .abf.yml first):"
echo "  $TGZ"
echo "  $HERE/opencode-${VERSION}-node_modules.tar.xz"
echo "  $HERE/models-dev-api.json"
echo "  $HERE/opentui-zig-0.8.1.tar.xz"
echo "  $HERE/fff-0.10.5-with-vendor.tar.xz"
echo "  $HERE/opencode-vite-natives.tar.xz"
echo "  $HERE/opencode-pty-vendor.tar.xz"
