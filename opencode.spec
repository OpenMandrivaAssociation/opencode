# OpenCode CLI. Production artifact is a bun --compile standalone binary.
# node_modules is vendored (see vendor-sources.sh) because ABF has no
# network. Native libraries (libopentui.so, libfff_c.so) are compiled
# from source in %build — we never ship npm prebuilt .so/.node files.
#
# Depends on bun, which is the hard package — see ../bun/bun.spec.
#
# Main package is the TUI/CLI. opencode-web is the same CLI with the
# Vite web frontend embedded (offline `opencode web`). Desktop/Electron
# is still out of scope.
#
# First time, on a networked machine (after bun is installed):
#   ./vendor-sources.sh
#   abb store opencode-*.tar.gz opencode-*-node_modules.tar.xz \
#     models-dev-api.json opentui-zig-*.tar.xz fff-*-with-vendor.tar.xz

# bun --compile emits a standalone binary; there is no debugsource.
%define debug_package %{nil}

%ifarch aarch64
%define bun_cpu arm64
%else
%define bun_cpu x64
%endif

Name:		opencode
Version:	1.18.22
Release:	5
Summary:	Open-source AI coding agent
Group:		Development/Other
License:	MIT
URL:		https://opencode.ai/
Source0:	https://github.com/anomalyco/opencode/archive/v%{version}/opencode-%{version}.tar.gz
# bun install --frozen-lockfile --ignore-scripts, then strip all natives
Source1:	opencode-%{version}-node_modules.tar.xz
# Snapshot of https://models.dev/api.json — fetched at vendor time, not build time
Source2:	models-dev-api.json
# OpenTUI 0.4.5 Zig core, ported to cooker Zig 0.17 (yoga + uucode + miniaudio)
Source3:	opentui-zig-0.4.5.tar.xz
# fff 0.9.4 crate sources + cargo-vendor (no rust-toolchain, no Windows import libs)
Source4:	fff-0.9.4-with-vendor.tar.xz

BuildRequires:	bun
BuildRequires:	nodejs
BuildRequires:	clang
BuildRequires:	zig
BuildRequires:	rust
BuildRequires:	cargo
BuildRequires:	esbuild
BuildRequires:	pkgconfig(libuv)
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

This package builds the official bun-compiled CLI from source. Native
TUI/search libraries are compiled from their Zig and Rust sources.
It does not download the prebuilt GitHub-release binaries.

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

# Relax the bun version pin. We build with bun 1.4; upstream package.json
# still says bun@1.3.14. Nix does the same substitution.
sed -i \
	's/throw new Error(`This script requires bun@/console.warn(`Warning: This script requires bun@/' \
	packages/script/src/index.ts

tar -xf %{S:1}
tar -xf %{S:3}
tar -xf %{S:4}

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

%build
export HOME=$(mktemp -d)
export OPENCODE_VERSION=%{version}
export OPENCODE_CHANNEL=prod
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export MODELS_DEV_API_JSON="$PWD/models-dev-api.json"
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
	cd fff-0.9.4
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
FFF_SO="$PWD/fff-0.9.4/target/release/libfff_c.so"
test -f "$FFF_SO"

# --- libopentui.so from Zig 0.17-ported sources ---
(
	cd opentui-zig-0.4.5
	zig build -Doptimize=ReleaseFast
)
OPENTUI_SO=$(find opentui-zig-0.4.5 -name libopentui.so | head -n1)
test -n "$OPENTUI_SO" -a -f "$OPENTUI_SO"

# bun --compile only embeds statically analyzable type:file imports.
# Stage host-arch packages that look like the npm optional wrappers,
# but with the .so we just compiled.
stage_opentui() {
	local dest="$1"
	mkdir -p "$dest"
	cat > "$dest/package.json" <<EOF
{
  "name": "@opentui/core-linux-%{bun_cpu}",
  "version": "0.4.5",
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
	mkdir -p "$dest"
	cat > "$dest/package.json" <<EOF
{
  "name": "@ff-labs/fff-bin-linux-%{bun_cpu}-gnu",
  "version": "0.9.4",
  "main": "libfff_c.so",
  "os": ["linux"],
  "cpu": ["%{bun_cpu}"],
  "libc": ["glibc"]
}
EOF
	cp -a "$FFF_SO" "$dest/libfff_c.so"
}

# Isolated bun layout plus classic node_modules so either resolver works.
stage_opentui "node_modules/@opentui/core-linux-%{bun_cpu}"
stage_opentui "node_modules/.bun/node_modules/@opentui/core-linux-%{bun_cpu}"
stage_fff "node_modules/@ff-labs/fff-bin-linux-%{bun_cpu}-gnu"
stage_fff "node_modules/.bun/node_modules/@ff-labs/fff-bin-linux-%{bun_cpu}-gnu"

# Next to the already-vendored @opentui/core / @ff-labs/fff-bun installs.
for coredir in node_modules/.bun/@opentui+core@*/node_modules; do
	[ -d "$coredir" ] || continue
	stage_opentui "$coredir/@opentui/core-linux-%{bun_cpu}"
done
for fffdir in node_modules/.bun/@ff-labs+fff-bun@*/node_modules/@ff-labs; do
	[ -d "$fffdir" ] || continue
	stage_fff "$fffdir/fff-bin-linux-%{bun_cpu}-gnu"
done

# esbuild ignores ESBUILD_BINARY_PATH=/usr/bin/esbuild on purpose.
# Point it at a copy so vite can use the system binary.
mkdir -p .tools
cp -a /usr/bin/esbuild .tools/esbuild
export ESBUILD_BINARY_PATH="$PWD/.tools/esbuild"

# Vite 7 may try optional lightningcss/rollup natives we stripped.
# Force postcss + no native CSS minify for the offline app build.
if [ -f packages/app/vite.config.ts ]; then
	sed -i '/build: {/a\
    cssMinify: false,' packages/app/vite.config.ts
fi

cd packages/opencode
# TUI/CLI only (main package). FFF_LIBC=gnu: OpenMandriva is glibc.
bun --bun ./script/build.ts --single --skip-install --skip-embed-web-ui
mkdir -p ../../dist-tui
cp -a dist/opencode-*/bin/opencode ../../dist-tui/opencode
bun --bun ./script/schema.ts schema.json
# Same CLI with packages/app/dist embedded (opencode-web subpackage).
bun --bun ./script/build.ts --single --skip-install
mkdir -p ../../dist-web
cp -a dist/opencode-*/bin/opencode ../../dist-web/opencode
cd -

%install
install -Dm0755 dist-tui/opencode \
	%{buildroot}%{_bindir}/opencode
install -Dm0755 dist-web/opencode \
	%{buildroot}%{_bindir}/opencode-web
install -Dm0644 packages/opencode/schema.json \
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
