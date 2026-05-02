# gptimage2生图
<img width="1239" height="1505" alt="PixPin_2026-04-26_22-36-58" src="https://github.com/user-attachments/assets/5b989f87-7ee9-4ad6-93b0-147ad3f3735f" />

AstrBot 插件，提供 `/gptimage2` 指令，支持：

- 文字生成图片
- 引用图片或直接发图后图生图
- 自动识别 `21:9`、`四比三`、`1664x928` 这类比例/尺寸描述
- `auto` / `responses` / `chat_completions` / `images` 四种 OpenAI 兼容路由

示例：

- `/gptimage2 生成一个赛博朋克猫娘海报`
- `/gptimage2 21:9 生成一个电影级宇宙战舰封面`
- `/gptimage2 四比三 生成一个复古像素风游戏封面`
- 引用一张图后发送 `/gptimage2 生成成吉卜力风格`

默认规则：

- 文生图默认 `default_resolution`，初始为 `3:4`
- 图生图默认尽量保持原图比例
- 如果指定比例，会优先使用插件内置的已验收尺寸别名
- `free_only_resolutions` 默认开启，只使用 Free 账号可承受的低像素尺寸；关闭后使用 4K / Paid 尺寸

插件配置时只需要填写：

- `base_url`
- `api_key`
- `route_mode`

可选配置：

- `user_whitelist`：限制允许调用的 QQ / 用户 ID，多个值可用逗号、空格或换行分隔；留空则不限制
- `deny_message`：非白名单用户触发时返回的自定义提示文案
- `default_resolution`：未指定比例或尺寸时的默认比例，可选 `1:1`、`3:2`、`2:3`、`4:3`、`3:4`、`16:9`、`9:16`、`21:9`、`9:21`
- `free_only_resolutions`：开启时只用 Free 尺寸；关闭时使用 4K / Paid 尺寸

Free 模式建议 NewAPI 侧提前开放这些模型别名：

- `gpt-image-2-1248x1248(1:1)`
- `gpt-image-2-1536x1024(3:2)`
- `gpt-image-2-1024x1536(2:3)`
- `gpt-image-2-1440x1072(4:3)`
- `gpt-image-2-1072x1440(3:4)`
- `gpt-image-2-1664x928(16:9)`
- `gpt-image-2-928x1664(9:16)`
- `gpt-image-2-1904x816(21:9)`
- `gpt-image-2-816x1904(9:21)`

Paid / 4K 模式还会使用：

- `gpt-image-2-2880x2880(1:1)`
- `gpt-image-2-3456x2304(3:2)`
- `gpt-image-2-2304x3456(2:3)`
- `gpt-image-2-3264x2448(4:3)`
- `gpt-image-2-2448x3264(3:4)`
- `gpt-image-2-3840x2160(16:9)`
- `gpt-image-2-2160x3840(9:16)`
- `gpt-image-2-3808x1632(21:9)`
- `gpt-image-2-1632x3808(9:21)`
