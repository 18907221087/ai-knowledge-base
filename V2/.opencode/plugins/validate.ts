/**
 * OpenCode Plugin Hook — 写入文章时自动触发 JSON 校验
 *
 * 当 Agent 使用 write 或 edit 工具修改 knowledge/articles/ 下的文件时，
 * 自动运行 validate_json.py 校验脚本，确保文章格式合规。
 *
 * 基于 OpenCode Plugin API：
 * - 事件: tool.execute.after（工具执行后触发）
 * - 输入: input.tool（工具名）、input.args.file_path / input.args.filePath（文件路径）
 * - 执行: Bun Shell API（$ 模板字符串）
 */

import type { Plugin } from "@opencode-ai/plugin"

export const ValidateHook: Plugin = async ({ $ }) => {
  return {
    "tool.execute.after": async (input) => {
      // 只在 write 或 edit 工具执行后触发
      const tool = input.tool?.toLowerCase() ?? ""
      if (tool !== "write" && tool !== "edit") {
        return
      }

      // 获取文件路径（兼容两种命名风格）
      const filePath: string | undefined =
        input.args?.file_path ?? input.args?.filePath

      if (!filePath) {
        return
      }

      // 只校验 knowledge/articles/ 目录下的 JSON 文件
      if (!filePath.includes("knowledge/articles/") || !filePath.endsWith(".json")) {
        return
      }

      console.log(`[validate-hook] 检测到文章写入: ${filePath}`)

      // 运行 JSON 格式校验
      // 使用 .nothrow() 避免非零退出码导致进程挂起
      const validateResult = await $`python3 hooks/validate_json.py ${filePath}`.nothrow()

      if (validateResult.exitCode !== 0) {
        console.error(`[validate-hook] ❌ 格式校验失败:`)
        console.error(validateResult.stdout.toString())
        console.error(validateResult.stderr.toString())
        return
      }

      console.log(`[validate-hook] ✅ 格式校验通过`)

      // 运行质量评分
      const qualityResult = await $`python3 hooks/check_quality.py ${filePath}`.nothrow()

      if (qualityResult.exitCode !== 0) {
        console.warn(`[validate-hook] ⚠️ 质量评分低于 B 级:`)
        console.warn(qualityResult.stdout.toString())
      } else {
        console.log(`[validate-hook] ✅ 质量评分达标`)
      }
    },
  }
}

export default ValidateHook
