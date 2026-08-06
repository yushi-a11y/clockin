#!/usr/bin/env bash
#
# ClockIn dingtalk-faq Edge Function 一键部署脚本
# 用法: ./deploy-dingtalk-faq.sh [supabase-project-path]
#
# 示例:
#   ./deploy-dingtalk-faq.sh
#   ./deploy-dingtalk-faq.sh ~/projects/clockin-supabase
#

set -euo pipefail

# 当前脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Edge Function 源目录
SRC_FUNC_DIR="${SCRIPT_DIR}/cloud-sync/dingtalk-faq"

# Supabase 项目目录：优先使用命令行参数，否则尝试向上查找 supabase/config.toml
if [ "$#" -ge 1 ]; then
  PROJECT_DIR="$(cd "$1" && pwd)"
else
  # 从脚本所在目录向上查找 supabase/config.toml
  SEARCH_DIR="${SCRIPT_DIR}"
  PROJECT_DIR=""
  while [ "$SEARCH_DIR" != "/" ]; do
    if [ -f "${SEARCH_DIR}/supabase/config.toml" ]; then
      PROJECT_DIR="$SEARCH_DIR"
      break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
  done
fi

if [ -z "${PROJECT_DIR}" ]; then
  echo "错误：未找到 Supabase 项目目录（缺少 supabase/config.toml）。" >&2
  echo "请在 ClockIn 的 Supabase 项目根目录下运行本脚本，或传入项目路径：" >&2
  echo "  $0 /path/to/your/supabase-project" >&2
  exit 1
fi

DEST_FUNC_DIR="${PROJECT_DIR}/supabase/functions/dingtalk-faq"

echo "==============================================="
echo "ClockIn dingtalk-faq Edge Function 部署脚本"
echo "==============================================="
echo "Supabase 项目目录: ${PROJECT_DIR}"
echo "Edge Function 源:  ${SRC_FUNC_DIR}"
echo ""

# 检查依赖（优先使用 PATH 中的 supabase，否则使用脚本同目录下的 bin/supabase）
SUPABASE_BIN=""
if command -v supabase >/dev/null 2>&1; then
  SUPABASE_BIN="supabase"
elif [ -x "${SCRIPT_DIR}/bin/supabase" ]; then
  SUPABASE_BIN="${SCRIPT_DIR}/bin/supabase"
fi

if [ -z "${SUPABASE_BIN}" ]; then
  echo "错误：未找到 supabase CLI。请先安装：" >&2
  echo "  macOS: brew install supabase/tap/supabase" >&2
  echo "  npm:   npm install -g supabase" >&2
  echo "  其它:  https://supabase.com/docs/guides/cli/getting-started" >&2
  exit 1
fi

echo "✓ supabase CLI 已安装: $(${SUPABASE_BIN} --version)"

# 检查源文件是否存在
if [ ! -d "${SRC_FUNC_DIR}" ]; then
  echo "错误：Edge Function 源目录不存在: ${SRC_FUNC_DIR}" >&2
  exit 1
fi

if [ ! -f "${SRC_FUNC_DIR}/index.ts" ]; then
  echo "错误：源目录缺少 index.ts: ${SRC_FUNC_DIR}/index.ts" >&2
  exit 1
fi

echo "✓ Edge Function 源文件完整"

# 复制函数到 Supabase 项目
echo ""
echo "→ 复制 dingtalk-faq 到 Supabase 项目..."
mkdir -p "$(dirname "${DEST_FUNC_DIR}")"
rm -rf "${DEST_FUNC_DIR}"
cp -R "${SRC_FUNC_DIR}" "${DEST_FUNC_DIR}"
echo "✓ 已复制到: ${DEST_FUNC_DIR}"

# 部署
echo ""
echo "→ 部署 Edge Function..."
cd "${PROJECT_DIR}"
"${SUPABASE_BIN}" functions deploy dingtalk-faq --no-verify-jwt

# 提取 project ref 并输出调用地址
echo ""
echo "==============================================="
echo "部署完成"
echo "==============================================="

PROJECT_REF=""
PROJECT_REF="$("${SUPABASE_BIN}" projects list --format json 2>/dev/null | grep -o '"ref": "[^"]*"' | head -1 | cut -d'"' -f4 || true)"

if [ -z "${PROJECT_REF}" ] && [ -f "${PROJECT_DIR}/supabase/config.toml" ]; then
  PROJECT_REF="$(grep -E '^project_id\s*=' "${PROJECT_DIR}/supabase/config.toml" | head -1 | sed 's/.*=\s*"\([^"]*\)".*/\1/' || true)"
fi

if [ -n "${PROJECT_REF}" ]; then
  echo "调用地址:"
  echo "  https://${PROJECT_REF}.supabase.co/functions/v1/dingtalk-faq"
else
  echo "调用地址请在 Supabase Dashboard → Edge Functions → dingtalk-faq 中查看"
fi

echo ""
echo "下一步："
echo "  1. 在钉钉群中添加 outgoing 机器人"
echo "  2. 将上面的调用地址填入「消息接收地址」"
echo "  3. @机器人提问测试"
