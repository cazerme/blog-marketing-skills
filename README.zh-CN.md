[English](README.md) | 简体中文

# blog-marketing-skills

为博客文章做 **SEO**（Google 排名）和 **GEO**（被 Gemini 这类 AI 引擎引用）优化的 Claude Code 技能。构建在开源技能包 [aaron-marketing](https://github.com/aaron-he-zhu/aaron-marketing-skills) 之上：本插件负责编排它的审计/写作技能，并自带一套确定性的、fail-closed 的引擎，安全地原地修改你的 HTML 或 Markdown 文件。

> **状态：v0.5。** 一个技能（`blog-seo-geo`）+ 一个 agent（`roadtrip-blogger`）。技能的能力与边界见[能力边界](#能力边界v04)。

## roadtrip-blogger agent

每次运行生成一篇完整、可直接发布的**北美路线 roadtrip 博客**——用你站点自己的格式和文风，并且**保证与已发布内容不重复**：

- 通过阅读你的站点自动发现发布约定（文章目录、注册表/front matter、标记词汇表），写出"原生长相"的文章
- 三级去重门禁，背后是覆盖账本（`<文章目录>/.coverage.md`）：路线不重写、主关键词不自我蚕食、别的文章"拥有"的事实只链接不复述
- 不编造具体信息：关键事实经官方来源核实，或以免责/不过时的方式书写
- 按你的约定注册文章、用本插件的机械引擎自检、更新账本后交接——**从不 commit、不部署**

在装了本插件的任何项目里直接说"生成一篇新的 roadtrip 博客"（可指定路线/关键词），或显式召唤 `roadtrip-blogger` agent。配合对新文章跑 `/blog-marketing:blog-seo-geo`，就是完整的"生成 → 优化"闭环。

## GitHub Action——定时自动生成博客

本仓库同时是一个 GitHub Action：按你设定的日程运行 roadtrip-blogger agent，每篇新文章以 **Pull Request** 形式送达（绝不直推默认分支）。在你博客仓库的 Secrets 里添加 `ANTHROPIC_API_KEY`，然后：

```yaml
# .github/workflows/daily-blog.yml
name: Daily blog post
on:
  schedule:
    - cron: "0 6 * * *"     # 每天一篇，06:00 UTC
  workflow_dispatch:          # 外加一个手动按钮
permissions:
  contents: write
  pull-requests: write
concurrency:
  group: blog-generation      # 防止两次运行竞争覆盖账本
  cancel-in-progress: false
jobs:
  generate:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: cazerme/blog-marketing-skills@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          # topic: "icefields parkway itinerary"   # 可选；不填则自动选题
          # working_directory: sites/blog          # 可选，monorepo 用
```

输入：`anthropic_api_key`（必填）· `topic` · `model` · `working_directory` · `create_pr` / `push_branch` · `base_branch` · `github_token`。输出：`post_file`、`branch`、`pr_url`。

每个 PR 都带 agent 交接报告的入口——**合并前先看易腐声明表**（封路/许可/费用这类会过期的事实）。每次运行消耗你 Anthropic 账户的真实 API 费用，cron 频率就是成本旋钮。记得把 `<文章目录>/.coverage.md` 提交入库——它是历次运行之间的去重记忆。

### 优化器 action（`/optimize`）

SEO/GEO 优化器以**子 action** 形式住在同一仓库（GA Marketplace 一个仓库只上架一个条目——生成器占门面，优化器按路径引用）：

```yaml
      - uses: cazerme/blog-marketing-skills/optimize@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          post_file: posts/my-post.md
          # keyword: "目标关键词"    # 可选；不填自动推导
```

它运行 `blog-seo-geo` 技能（会在 runner 上装好 aaron-marketing 依赖），**只把文章文件本身提交进 PR**（备份和报告留在 runner 上——报告内容直接变成 PR 正文），并且幂等：已优化过的文章会得到 `changed: false`、不开 PR。

### 完整闭环：生成 → 优化 → 一次人审

把两个 action 链在同一个每日 workflow 里，每篇新文章送到你手上时已经是优化完成体（配方见英文版 README 的 "The full loop" 一节）。

## 它做什么

```
/blog-marketing:blog-seo-geo path/to/post.html [目标关键词]
/blog-marketing:blog-seo-geo posts/2026-07-08-my-post.md [目标关键词]
```

1. 把文章解析成内容块，跑一套确定性机械检查（title/meta、标题层级、图片 alt、链接……）→ 基线分
2. 用 `aaron-marketing:on-page-seo-auditor` 诊断问题
3. 用 `aaron-marketing:content-writer`（refresh 模式）改写内容块——事实、链接、图片全部保留，不编造任何东西
4. 用 `aaron-marketing:geo-content-optimizer` 跑 **GEO pass**：把关键段落改写成 AI 引擎（Gemini 式引用）可直接摘引的形态，必要时补答案/FAQ 块——只复述文章已有的内容
5. 用 `aaron-marketing:serp-markup-builder` 生成头部标记：title + meta description 直接写回完整 HTML 文档和 Markdown front matter；OG/Twitter/JSON-LD 以可直接粘贴的形式进报告
6. **安全写回**：先落备份，再原子写入——任何链接/图片/结构会丢失时整个计划被拒（fail-closed）
7. 在 `.seo-optimizer/reports/` 生成报告：关键词依据、改了什么为什么、已解决的问题、机械分前后对比、模板建议

所有副产物都放在 `<输入文件目录>/.seo-optimizer/` 里——静态站点生成器和构建工具约定忽略点开头目录，所以备份和报告**永远不会泄漏进你发布的网站**（也不会撞上 Jekyll 对 `_posts/` 的扫描）。`backups/<文件名>.original` 是你第一次运行前的原文，**无论重复优化多少次都不会被覆盖**；每次运行还会另存一份带时间戳的运行前快照。建议把 `.seo-optimizer/` 加进 `.gitignore`（没加的话技能会提醒你）。

### Markdown 博客（Jekyll / Hugo / GitHub Pages）

`.md` 文章是一等输入。front matter 的 `title:` 和 `description:` 被当作文章的头部：既参与检查，也**直接原地修改**（已有 front matter 缺键会补上）。正文优化与 HTML 完全一致——并且解析器硬性保护改写绝不能碰的东西：**代码围栏、内嵌原始 HTML、表格、分隔线**。复杂的 front matter 值（嵌套列表、多行）一律不动。没有 front matter 的文章按下面的片段模式处理。

### 片段模式（模板驱动的博客）

如果你的文章是**正文片段**（没有 `<html>/<head>`——由服务器或 SSG 注入页面模板，例如 Flask/Jinja/Hugo partials），技能会自动识别：正文优化照常写回片段文件，而所有头部项（title、meta description、canonical、OG/Twitter、JSON-LD）以可直接粘贴的成品值进报告，并注明各自属于哪里（你的模板/文章注册表）。头部类机械检查标记为 `skipped` 而非误判失败——它们考核的是你的模板，不是这个片段。

## 安装

需要 [Claude Code](https://claude.com/claude-code) 和 aaron-marketing 插件：

```
/plugin marketplace add aaron-he-zhu/aaron-marketing-skills
/plugin install aaron-marketing@aaron

/plugin marketplace add cazerme/blog-marketing-skills
/plugin install blog-marketing@blog-marketing-skills
```

然后在你的博客项目里：

```
/blog-marketing:blog-seo-geo posts/my-post.html
```

建议先拿自带样章练手：把 `examples/sample-post.html` 复制到任意位置，对它跑一次命令。

`/plugin update blog-marketing` 之后需要重启 Claude Code（或运行 `/reload-plugins`）——在此之前会话仍使用之前加载的版本。技能在每次运行总结的末尾自报版本号，缓存过期一眼可见。

## 能力边界（v0.4）

| | |
|---|---|
| ✅ 输入 | **本地 HTML 或 Markdown 文件**，文章内容必须在文件里——完整 HTML 文档、正文片段、或带 YAML front matter 的 `.md`（手写 HTML、Jekyll/Hugo/GitHub Pages 源文件、提交在仓库里的服务端渲染页面） |
| ✅ 输出 | 同一个文件原地优化；报告 + 永不覆盖的原文备份 + 时间戳快照，都在 `.seo-optimizer/` 下；片段/无 front matter 的 markdown 的头部项进报告，绝不瞎猜着写进文件 |
| ✅ 语言/引擎 | 英文内容；SEO 面向 Google，GEO 面向 Gemini 式 AI 引用 |
| ❌ 线上 URL | 不支持：没有"原文件"可写回。改仓库里的源文件，然后部署 |
| ❌ SPA 空壳/构建产物 | 拒绝并说明原因——正确的编辑对象是你的内容源文件，不是编译输出 |
| ❌ 技术 SEO | 爬取、sitemap、Core Web Vitals 是站点级问题，不在范围内 |

## 安全保证

- **写入白名单**：只碰你的输入文件（备份先落进 `.seo-optimizer/backups/`）、报告文件和临时文件。其他一概不动——连你的 `.gitignore` 都不动（技能只建议那行配置，由你自己加）。
- **Fail-closed**：未知块、丢链接/丢图、结构损坏、运行中文件被改 ⇒ 整个计划被拒，**一个字都不写**。
- **逐字节拼接**：未编辑区域从构造上保证逐字节不变——文档从不重新序列化。Markdown 里代码围栏和内嵌 HTML 在结构上就不可编辑。
- **数字门禁**：改写中出现的任何数字，只要在原文档里不存在，整个计划即被拒绝（0–10 的整数豁免，"eight steps"→"8 steps" 仍可行）。编造或写串的统计数字**在机械层面就到不了你的文件**——这是引擎强制，不是提示词承诺。
- **覆盖率诚实**：每次运行都报告解析器实际识别了多少比例的可见正文；低于 70% 时报告开头会挂明确的"部分覆盖"声明，绝不把半份诊断当整份交付。
- **不编造**：改写只重组、收紧文章已有的内容；新事实、新数据、新论断越界（数字类还会被机械拒绝，见上）。
- 脚本只用 Python 标准库——不需要 pip install，零网络访问。

## 关于机械分

这个分数是确定性的**启发式基线**——考核的是常规做法（title 长度、关键词位置、标题层级、alt 文本），不是编辑质量的裁决。刻意的非常规选择（比如用悬念式数据研究标题而不是关键词式标题）可能恰恰适合你的页面，却会在这里扣分。把低于 100 当作"值得看一眼"，而不是"必须修"；技能本身也被要求对足够好的内容保持克制。

## 路线图

URL 只读体检、完整文档的头部标记注入（OG/Twitter/JSON-LD 块）、图片 `alt` 编辑、MDX/setext 标题的可编辑化、显式授权的第二写入目标（如 `--meta-target` 指向文章注册表文件）。

## 开发

```
python3 -m unittest discover tests    # 引擎 round-trip + fail-closed 测试套件
claude plugin validate .              # 清单校验
```

## 许可证

MIT。基于 aaron-marketing 16.1.0 测试。
