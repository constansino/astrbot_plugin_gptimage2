# gptimage2生图

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

- 文生图默认 `3:4`
- 图生图默认尽量保持原图比例
- 如果指定比例，会优先使用插件内置的已验收尺寸别名

插件配置时只需要填写：

- `base_url`
- `api_key`
- `route_mode`

建议 NewAPI 侧提前开放这些模型别名：

- `gpt-image-2-1248x1248(1:1)`
- `gpt-image-2-1536x1024(3:2)`
- `gpt-image-2-1024x1536(2:3)`
- `gpt-image-2-1440x1072(4:3)`
- `gpt-image-2-1072x1440(3:4)`
- `gpt-image-2-1664x928(16:9)`
- `gpt-image-2-928x1664(9:16)`
- `gpt-image-2-1904x816(21:9)`
- `gpt-image-2-816x1904(9:21)`
