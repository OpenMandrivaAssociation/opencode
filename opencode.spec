# OpenCode CLI. Production artifact is a bun --compile standalone binary.
# node_modules is vendored (see vendor-sources.sh) because ABF has no
# network. Native code is compiled in %%build. npm prebuilt ELF and
# .node files are not shipped. Photon and tree-sitter stay as the
# WebAssembly modules those packages import.
#
# Depends on bun, which is the hard package — see ../bun/bun.spec.
# Cooker bun is 1.4.0; upstream asks for bun@1.4.4. %%prep relaxes that
# check the same way nix does.
#
# Main package is the TUI/CLI. opencode-web is the same CLI with the
# Vite web frontend embedded (offline `opencode web`). Desktop/Electron
# is out of scope.
#
# opencode-pty (persistent terminals) links Ghostty lib-vt, which is
# pinned to Zig 0.16. Cooker Zig is 0.17, so that binary is not built.
# The CLI looks for `opencode-pty` on PATH. Ordinary PTYs use bun-pty.
#
# First time, on a networked machine (after bun is installed):
#   ./vendor-sources.sh
#   abb store opencode-VERSION.tar.gz opencode-VERSION-node_modules.tar.xz \
#     models-dev-api.json opentui-zig-0.8.0.tar.xz \
#     fff-0.10.5-with-vendor.tar.xz opencode-vite-natives.tar.xz
# Remove a replaced key from .abf.yml before abb store reuses its name.
# Do not store opencode-pty-vendor.tar.xz. Ghostty lib-vt is Zig 0.16.

# bun --compile emits a standalone binary; there is no debugsource.
%define debug_package %{nil}

%ifarch aarch64
%define bun_cpu arm64
%else
%define bun_cpu x64
%endif

# %%{_gnu} is the toolchain ABI suffix: -gnu, -musl, -uclibc,
# plus ARM variants (-gnueabihf, -musleabihf, -uclibceabihf, ...).
%define libc_family %(echo '%{_gnu}' | sed 's/^-//;s/eabi.*//')

# fff/opentui/vite JS loaders only know gnu vs musl path names.
# The matching .so/.node is always compiled here against the host libc.
# musl uses the *-musl names; glibc and uclibc-ng use the non-musl names.
%if "%{libc_family}" == "musl"
%define fff_libc musl
%define opentui_libc musl
%define opentui_pkg_suffix -musl
%define native_abi musl
%else
%define fff_libc gnu
%define opentui_libc glibc
%define opentui_pkg_suffix %{nil}
%define native_abi gnu
%endif

Name:		opencode
Version:	2.2.5
Release:	1
Summary:	Open-source AI coding agent
Group:		Development/Other
License:	MIT
URL:		https://opencode.ai/
Source0:	https://github.com/anomalyco/opencode/archive/v%{version}/opencode-%{version}.tar.gz
# bun install --frozen-lockfile --ignore-scripts, then strip all natives.
# Includes packages/*/node_modules symlinks into node_modules/.bun.
Source1:	opencode-%{version}-node_modules.tar.xz
# Trimmed models catalog from packages/core/script/update-models-snapshot.ts
# (https://models.opencode.ai). Fetched at vendor time, not build time.
Source2:	models-dev-api.json
# OpenTUI 0.8.0 Zig core, ported to cooker Zig 0.17 (yoga + uucode + ghostty)
Source3:	opentui-zig-0.8.0.tar.xz
# fff 0.10.5 crate sources + cargo-vendor (no rust-toolchain, no Windows import libs)
Source4:	fff-0.10.5-with-vendor.tar.xz
# Rolldown 1.2.5 / Rollup 4.62.4 / lightningcss 1.33.0 and 1.32.0 /
# tailwind oxide 4.3.3 sources + cargo vendor. Compiled in %%build for
# the embedded web UI. Vite 8 bundles with Rolldown. vite-plugin-pwa's
# workbox-build loads Rollup. Vite loads lightningcss 1.33.
# @tailwindcss/node loads 1.32.
Source5:	opencode-vite-natives.tar.xz

BuildRequires:	bun
BuildRequires:	nodejs
BuildRequires:	clang
BuildRequires:	libstdc++-devel
BuildRequires:	zig
BuildRequires:	rust
BuildRequires:	cargo
BuildRequires:	python
BuildRequires:	git
BuildRequires:	make

# Runtime: the compiled binary shells out to rg for codebase search.
# OpenMandriva's rg is the grep-based C++ ripgrep implementation
# (ripgrep-compatible CLI, including --json / --hidden / --glob).
Requires:	rg
Requires:	git

# fzf is used by some picker flows; available in cooker.
Requires:	fzf

%description
OpenCode is an open-source AI coding agent. It talks to any LLM provider
(or a local model) and edits a project from a terminal UI.

This package builds the official bun-compiled CLI from source. The TUI
library (OpenTUI), the file finder (fff) and the web UI's Rolldown,
Rollup, lightningcss and Tailwind natives are compiled here against the
host libc. It does not ship prebuilt npm ELF or .node files.

The web frontend is not embedded here: `opencode web` proxies to
https://app.opencode.ai. For an offline UI, install opencode-web.

%package web
Summary:	OpenCode CLI with embedded web frontend
Group:		Development/Other
Requires:	rg
Requires:	git
Requires:	fzf

%description web
Same OpenCode CLI as the main package, but the Vite web frontend is
compiled in. `opencode-web web` serves that UI locally and does not
need https://app.opencode.ai.

This is a standalone bun --compile binary. It does not require the
opencode package.

%prep
%autosetup -p1 -n opencode-%{version}

# Relax the bun version pin. Cooker bun is 1.4.0; upstream package.json
# asks for bun@1.4.4. Nix does the same substitution.
sed -i \
	's/throw new Error(`This script requires bun@/console.warn(`Warning: This script requires bun@/' \
	packages/script/src/index.ts

tar -xf %{S:1}
tar -xf %{S:3}
tar -xf %{S:4}
tar -xf %{S:5}

# --single selects the target whose abi is undefined, which is glibc.
# On musl, select the musl entry instead. The ?? defaults already name
# glibc/gnu, and a musl entry carries abi: "musl" so they are not used.
OPENCODE_LIBC_FAMILY="%{libc_family}" python - <<'PY'
import os
from pathlib import Path
p = Path("packages/cli/script/build.ts")
text = p.read_text()
for needle in (
	'return item.abi === undefined',
	'item.abi ?? "glibc"',
	'item.abi ?? "gnu"',
):
	if needle not in text:
		raise SystemExit(f"build.ts libc define not found: {needle}")
if os.environ["OPENCODE_LIBC_FAMILY"] == "musl":
	text = text.replace(
		'return item.abi === undefined',
		'return item.abi === "musl"',
		1,
	)
	p.write_text(text)
PY

# Ghostty lib-vt is pinned to Zig 0.16 (revision in
# packages/process-daemon/ghostty-revision). Cooker Zig is 0.17, so
# there is no opencode-pty binary. Missing it must not fail the CLI
# build; persistent terminals then look for opencode-pty on PATH.
python - <<'PY'
from pathlib import Path
p = Path("packages/cli/script/opencode-pty.ts")
text = p.read_text()
old = """  const source = local
    ? path.resolve(local)
    : pty.resolve(`${name}/bin/${target.platform === "win32" ? "opencode-pty.exe" : "opencode-pty"}`)
"""
new = """  let source: string
  try {
    source = local
      ? path.resolve(local)
      : pty.resolve(`${name}/bin/${target.platform === "win32" ? "opencode-pty.exe" : "opencode-pty"}`)
  } catch (error) {
    console.warn(`opencode-pty native binary unavailable (${name}): ${error}`)
    return undefined
  }
"""
if old not in text:
	raise SystemExit("opencode-pty.ts resolve block not found")
p.write_text(text.replace(old, new, 1))
PY

# Anything that looks like a prebuilt native must not reach %build.
# The from-source .so files are staged later, after this sweep.
find node_modules packages -type f \( \
	-name '*.so' -o \
	-name '*.node' -o \
	-name '*.dll' -o \
	-name '*.dylib' -o \
	-name '*.exe' -o \
	-name '*.bare' -o \
	-name 'esbuild' \
	\) -delete 2>/dev/null || :
find node_modules packages -type f ! -name '*.js' ! -name '*.ts' ! -name '*.json' \
	! -name '*.md' ! -name '*.map' ! -name '*.wasm' -print0 2>/dev/null |
	xargs -0 -r file -N |
	awk -F': ' '$2 ~ /^(ELF|PE32|Mach-O|MS-DOS)/ { print $1 }' |
	xargs -r rm -f

install -m0644 %{S:2} models-dev-api.json
cp -a models-dev-api.json packages/core/src/models-dev/snapshot.txt

%build
set -o pipefail
export HOME=$(mktemp -d)
export OPENCODE_VERSION=%{version}
export OPENCODE_CHANNEL=prod
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export OPENCODE_MODELS_SNAPSHOT="$PWD/models-dev-api.json"
export npm_config_nodedir=/usr
export BUN_INSTALL_CACHE_DIR="$PWD/.bun-cache"
export npm_config_offline=true
export npm_config_ignore_scripts=true
export GIT_TERMINAL_PROMPT=0
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export CARGO_NET_OFFLINE=true
export CARGO_HOME="$PWD/.cargo-home"
mkdir -p "$CARGO_HOME"

# --- libfff_c.so from vendored Rust ---
(
	cd fff-0.10.5
	# Never let a rust-toolchain.toml talk to rustup; ABF is offline.
	rm -f rust-toolchain.toml
	# winapi 0.3.9 lists unused Windows-gnu import-lib crates as
	# target deps. cargo --offline still requires them in vendor/.
	# Drop the deps instead of shipping ~100MB of Windows .a files.
	if [ -f cargo-vendor/winapi/Cargo.toml ]; then
		sed -i \
			-e '/target.i686-pc-windows-gnu.dependencies.winapi-i686-pc-windows-gnu/,+1d' \
			-e '/target.x86_64-pc-windows-gnu.dependencies.winapi-x86_64-pc-windows-gnu/,+1d' \
			cargo-vendor/winapi/Cargo.toml
		python - <<'PY'
import hashlib, json
from pathlib import Path
p = Path("cargo-vendor/winapi/Cargo.toml")
cpath = Path("cargo-vendor/winapi/.cargo-checksum.json")
data = json.loads(cpath.read_text())
data["files"]["Cargo.toml"] = hashlib.sha256(p.read_bytes()).hexdigest()
cpath.write_text(json.dumps(data, separators=(",", ":")))
PY
	fi
	# --offline is enough: vendor replaces crates.io. --frozen
	# fights the winapi target-dep edit below.
	cargo build --release -p fff-c --offline
)
FFF_SO="$PWD/fff-0.10.5/target/release/libfff_c.so"
test -f "$FFF_SO"

# --- libopentui.so from the Zig 0.17 port of OpenTUI 0.8.0 ---
# Yoga is compiled by build.zig with the system c++ (addSystemCxxObject).
# Zig 0.17's CLI flag is --release=fast, not -Doptimize=ReleaseFast.
# The AMX-TF32 translate-c skip is already in this port's build.zig.
(
	cd opentui-zig-0.8.0
%if "%{libc_family}" == "musl"
%ifarch aarch64
	zig build --release=fast -Dlibrary-target=aarch64-linux-musl
%else
	zig build --release=fast -Dlibrary-target=x86_64-linux-musl
%endif
%else
%ifarch aarch64
	zig build --release=fast -Dlibrary-target=aarch64-linux-gnu.2.17
%else
	zig build --release=fast -Dlibrary-target=x86_64-linux-gnu.2.17
%endif
%endif
)
OPENTUI_SO=$(find opentui-zig-0.8.0 -name libopentui.so ! -path '*/.zig-cache/*' | head -n1)
test -n "$OPENTUI_SO" -a -f "$OPENTUI_SO"

# bun --compile only embeds statically analyzable type:file imports.
# Stage host-arch packages that look like the npm optional wrappers,
# but with the .so we just compiled.
stage_opentui() {
	local dest="$1"
	# bun isolated linker may have left a symlink here.
	rm -rf "$dest"
	mkdir -p "$dest"
	cat > "$dest/package.json" <<EOF
{
  "name": "@opentui/core-linux-%{bun_cpu}%{opentui_pkg_suffix}",
  "version": "0.8.0",
  "type": "module",
  "main": "index.js",
  "exports": {
    ".": {
      "bun": "./index.bun.js",
      "import": "./index.js"
    }
  },
  "os": ["linux"],
  "cpu": ["%{bun_cpu}"]
}
EOF
	printf '%s\n' \
		'const module = await import("./libopentui.so", { with: { type: "file" } })' \
		'export default module.default' \
		> "$dest/index.bun.js"
	printf '%s\n' \
		'import { fileURLToPath } from "node:url"' \
		'export default fileURLToPath(new URL("./libopentui.so", import.meta.url))' \
		> "$dest/index.js"
	cp -a "$OPENTUI_SO" "$dest/libopentui.so"
}

stage_fff() {
	local dest="$1"
	rm -rf "$dest"
	mkdir -p "$dest"
	cat > "$dest/package.json" <<EOF
{
  "name": "@ff-labs/fff-bin-linux-%{bun_cpu}-%{fff_libc}",
  "version": "0.10.5",
  "main": "libfff_c.so",
  "os": ["linux"],
  "cpu": ["%{bun_cpu}"],
  "libc": ["%{opentui_libc}"]
}
EOF
	cp -a "$FFF_SO" "$dest/libfff_c.so"
}

# Isolated bun layout plus classic node_modules so either resolver works.
stage_opentui "node_modules/@opentui/core-linux-%{bun_cpu}%{opentui_pkg_suffix}"
stage_opentui "node_modules/.bun/node_modules/@opentui/core-linux-%{bun_cpu}%{opentui_pkg_suffix}"
stage_fff "node_modules/@ff-labs/fff-bin-linux-%{bun_cpu}-%{fff_libc}"
stage_fff "node_modules/.bun/node_modules/@ff-labs/fff-bin-linux-%{bun_cpu}-%{fff_libc}"

# Next to the already-vendored @opentui/core / @ff-labs/fff-bun installs.
for coredir in node_modules/.bun/@opentui+core@*/node_modules; do
	[ -d "$coredir" ] || continue
	stage_opentui "$coredir/@opentui/core-linux-%{bun_cpu}%{opentui_pkg_suffix}"
done
for fffdir in node_modules/.bun/@ff-labs+fff-bun@*/node_modules/@ff-labs; do
	[ -d "$fffdir" ] || continue
	stage_fff "$fffdir/fff-bin-linux-%{bun_cpu}-%{fff_libc}"
done

# --- @parcel/watcher from the vendored C++ sources ---
# The CLI build rewrites watcher-binding.ts to
# require("@parcel/watcher-linux-$cpu-glibc"). node-gyp must not
# download headers; cooker has them under /usr/include/node.
# aarch64 keeps node-gyp under /usr/lib64, x86_64 under /usr/lib.
(
	cd node_modules/.bun/@parcel+watcher@2.5.1/node_modules/@parcel/watcher
	NODE_GYP=$(find /usr/lib /usr/lib64 -path '*/node-gyp/bin/node-gyp.js' -print -quit)
	test -n "$NODE_GYP"
	node "$NODE_GYP" rebuild --nodedir=/usr
)
WATCHER_NODE="$PWD/node_modules/.bun/@parcel+watcher@2.5.1/node_modules/@parcel/watcher/build/Release/watcher.node"
test -f "$WATCHER_NODE"

stage_watcher() {
	local dest="$1"
	rm -rf "$dest"
	mkdir -p "$dest"
	cat > "$dest/package.json" <<EOF
{
  "name": "@parcel/watcher-linux-%{bun_cpu}-%{opentui_libc}",
  "version": "2.5.1",
  "main": "watcher.node",
  "os": ["linux"],
  "cpu": ["%{bun_cpu}"]
}
EOF
	cp -a "$WATCHER_NODE" "$dest/watcher.node"
}
for watcher_dest in \
	packages/cli/node_modules/@parcel/watcher-linux-%{bun_cpu}-%{opentui_libc} \
	packages/core/node_modules/@parcel/watcher-linux-%{bun_cpu}-%{opentui_libc} \
	node_modules/@parcel/watcher-linux-%{bun_cpu}-%{opentui_libc} \
	node_modules/.bun/node_modules/@parcel/watcher-linux-%{bun_cpu}-%{opentui_libc}
do
	stage_watcher "$watcher_dest"
done

# --- Vite natives from source ---
# JS loaders pick linux-$cpu-gnu vs linux-$cpu-musl by filename only.
# The file we drop there is compiled against the host libc.
# Do not set NAPI_RS_NATIVE_LIBRARY_PATH: oxide, rolldown and
# lightningcss all honor it and would load the wrong addon.
# cargo-vendor copies are named in the checksum files; deleting them
# makes cargo --offline refuse the tree.
find vite-natives -path '*/cargo-vendor/*' -prune -o \
	\( -name rust-toolchain.toml -o -name rust-toolchain \) \
	-exec rm -f {} +

(
	cd vite-natives/rolldown-1.2.5
	cargo build --release -p rolldown_binding --offline
)
ROLLDOWN_SO="$PWD/vite-natives/rolldown-1.2.5/target/release/librolldown_binding.so"
test -f "$ROLLDOWN_SO"

(
	cd vite-natives/lightningcss-1.33.0
	cargo build --release -p lightningcss_node --offline
)
LIGHTNING_SO="$PWD/vite-natives/lightningcss-1.33.0/target/release/liblightningcss_node.so"
test -f "$LIGHTNING_SO"
# @tailwindcss/node 4.3.3 imports lightningcss 1.32, which Vite's
# config loads even though Vite itself uses 1.33.
(
	cd vite-natives/lightningcss-1.32.0
	cargo build --release -p lightningcss_node --offline
)
LIGHTNING32_SO="$PWD/vite-natives/lightningcss-1.32.0/target/release/liblightningcss_node.so"
test -f "$LIGHTNING32_SO"

(
	cd vite-natives/tailwindcss-4.3.3
	cargo build --release -p tailwind-oxide --offline
)
OXIDE_SO="$PWD/vite-natives/tailwindcss-4.3.3/target/release/libtailwind_oxide.so"
test -f "$OXIDE_SO"

# vite-plugin-pwa -> workbox-build parses with Rollup 4.62. native.js
# loads dist/rollup.<platform>.node before the optional npm package.
(
	cd vite-natives/rollup-4.62.4/rust
	rm -f bindings_napi/.cargo/config.toml bindings_wasm/.cargo/config.toml
	cargo build --release -p bindings_napi --offline
)
ROLLUP_SO="$PWD/vite-natives/rollup-4.62.4/rust/target/release/libbindings_napi.so"
test -f "$ROLLUP_SO"

# Stage the freshly built addons where the vendored JS loaders look.
# x64 glibc rolldown loads ../rolldown-binding.*.node from dist/shared
# (that is dist/). arm64 and musl load ./ from dist/shared. Both copies
# are the same file.
NATIVE_TRIPLE="linux-%{bun_cpu}-%{native_abi}"
find node_modules packages -path '*/rollup/dist' -type d |
while IFS= read -r dist; do
	cp -af "$ROLLUP_SO" "$dist/rollup.${NATIVE_TRIPLE}.node"
done
find node_modules packages -path '*/rolldown/package.json' -type f |
while IFS= read -r pkg; do
	root=$(dirname "$pkg")
	mkdir -p "$root/dist" "$root/dist/shared"
	cp -af "$ROLLDOWN_SO" "$root/dist/rolldown-binding.${NATIVE_TRIPLE}.node"
	cp -af "$ROLLDOWN_SO" "$root/dist/shared/rolldown-binding.${NATIVE_TRIPLE}.node"
done
find node_modules packages -path '*/lightningcss/package.json' -type f |
while IFS= read -r pkg; do
	ver=$(python -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' "$pkg")
	case "$ver" in
	1.33.0) cp -af "$LIGHTNING_SO" "$(dirname "$pkg")/lightningcss.${NATIVE_TRIPLE}.node" ;;
	1.32.0) cp -af "$LIGHTNING32_SO" "$(dirname "$pkg")/lightningcss.${NATIVE_TRIPLE}.node" ;;
	*) echo "unexpected lightningcss version $ver" >&2; exit 1 ;;
	esac
done
find node_modules packages -path '*/@tailwindcss/oxide/index.js' -type f |
while IFS= read -r index; do
	cp -af "$OXIDE_SO" "$(dirname "$index")/tailwindcss-oxide.${NATIVE_TRIPLE}.node"
done
test -n "$(find node_modules -path '*/rollup/dist/rollup.'"${NATIVE_TRIPLE}"'.node' -print -quit)"
test -n "$(find node_modules -name "rolldown-binding.${NATIVE_TRIPLE}.node" -print -quit)"
test -n "$(find node_modules -path '*/lightningcss@1.32.0*/lightningcss.'"${NATIVE_TRIPLE}"'.node' -print -quit)"
test -n "$(find node_modules -path '*/lightningcss@1.33.0*/lightningcss.'"${NATIVE_TRIPLE}"'.node' -print -quit)"
test -n "$(find node_modules -name "tailwindcss-oxide.${NATIVE_TRIPLE}.node" -print -quit)"

# bun's node:wasi is incomplete; run Vite under Node with the .node files.
if [ -f packages/app/package.json ]; then
	sed -i 's|"build": "vite build"|"build": "node ./node_modules/vite/bin/vite.js build"|' \
		packages/app/package.json
fi

# schema.ts imports prettier. The isolated install links it from
# packages that format generated sources, not from the cli package.
if [ ! -e packages/cli/node_modules/prettier ]; then
	prett=$(find node_modules/.bun -maxdepth 1 -type d -name 'prettier@*' | head -n1)
	test -n "$prett"
	ln -s "../../../$prett/node_modules/prettier" packages/cli/node_modules/prettier
fi

cd packages/cli
# TUI/CLI only. A second pass embeds packages/app/dist (opencode-web).
bun --bun ./script/build.ts --single --skip-install --skip-web-ui
mkdir -p ../../dist-tui
cp -a dist/cli-*/bin/opencode ../../dist-tui/opencode
bun --bun ./script/schema.ts "$PWD/schema.json"
bun --bun ./script/build.ts --single --skip-install
mkdir -p ../../dist-web
cp -a dist/cli-*/bin/opencode ../../dist-web/opencode
cd -

%install
install -Dm0755 dist-tui/opencode \
	%{buildroot}%{_bindir}/opencode
install -Dm0755 dist-web/opencode \
	%{buildroot}%{_bindir}/opencode-web
install -Dm0644 packages/cli/schema.json \
	%{buildroot}%{_datadir}/opencode/schema.json

%check
export HOME=$(mktemp -d)
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export PATH="%{buildroot}%{_bindir}:/usr/bin:$PATH"
opencode --version
opencode-web --version

%files
%license LICENSE
%doc README.md
%{_bindir}/opencode
%dir %{_datadir}/opencode
%{_datadir}/opencode/schema.json

%files web
%license LICENSE
%{_bindir}/opencode-web
