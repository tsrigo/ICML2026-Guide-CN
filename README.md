# 📚 ICML 2026 全部接收论文 · 中文导读

> 大模型替你读完了 ICML 2026 全部 **6,567** 篇接收论文 🤯
> 中文六维度导读 · **8 一级 / 76 二级 / 95 三级**目录 · ⭐ Spotlight 高亮

🔗 **在线浏览**：<https://JenniferZhao0531.github.io/ICML2026-Guide-CN/>

---

## ✨ 这是什么

把 ICML 2026 全部 **6,567** 篇接收论文整理成一个零依赖的静态网页。每篇论文自动生成六个维度的中文分析：

| 维度 | 说明 |
| --- | --- |
| 🎯 研究动机 | 论文出发点 |
| ❓ 解决问题 | 具体要解决什么 |
| 🔍 现象分析 | 观察 / 经验性发现 |
| 🛠️ 主要方法 | 技术方案概览 |
| 📊 数据与实验 | 用了什么数据、怎么评 |
| ⭐ 主要贡献 | 一句话定位 |

并按**三级目录**组织：

- **一级**：8 个 ICML 官方研究方向
- **二级**：每个一级下 LLM 打 5–13 个细分小类，全站 **76** 个二级
- **三级**：对论文数 ≥150 的 11 个"肥桶"再切一刀，全站 **95** 个三级（如 *RLHF/对齐* / *扩散理论* / *Agent 与工具使用* …）

⭐ 全部 **575 篇 Spotlight** 论文在卡片上加金色徽章 + 边条高亮，顶部一键筛选只看 Spotlight。

---

## 📁 8 个一级大类（按"方法 → 基础 → 应用/影响"分组）

**核心方法**：深度学习 (2816) · 强化学习 (886) · 通用机器学习 (286)
**数学基础**：优化 (546) · 概率方法 (364) · 理论 (362)
**下游与影响**：应用 (631) · 社会议题 (676)

> 每个一级下都有 6–15 个二级小类；11 个 ≥150 篇的二级"肥桶"还会再切一层三级。详见网页左侧折叠导航。

---

## 🚀 用法

### 直接看
打开 [在线网页](https://JenniferZhao0531.github.io/ICML2026-Guide-CN/) 或本地的 `index.html`：

- **左侧三级导航**：点一级展开二级；点二级（带 ▶ 的肥桶）再展开三级；点叶子跳转
- **顶部 chip**：一键筛选 `📚 全部 / ⭐ Spotlight 575 篇`
- **顶部搜索框**：标题 / 作者全文检索（搜索时各层计数动态重算并自动展开有结果的分组）
- **按需加载**：页面打开时只渲染当前可见分组的少量论文，滚动或点击“加载更多”再补充，避免一次性铺开 6,567 张卡片
- **本地收藏**：每张论文卡右上角有灰色星标，点击后变黄并保存在当前浏览器的 `localStorage`
- **每篇论文卡片**：标题点 Google Scholar（ICML 2026 OpenReview forum 暂未公开）；⭐ Spotlight 徽章；六维度中文分析；展开查看完整 Abstract
- **右下角 ↑**：一键回到顶部

### 本地浏览
```bash
git clone https://github.com/JenniferZhao0531/ICML2026-Guide-CN.git
cd ICML2026-Guide-CN
open index.html      # macOS（直接双击也行）
```

### 自己跑流水线

完整流水线四步，所有 LLM 调用走 OpenAI 兼容接口，**用你自己的 key**：

```bash
pip install openai tqdm requests
```

在仓库根目录建一个 `.env` 文件（已在 `.gitignore`）：

```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

> `OPENAI_BASE_URL` 也可以填 DeepSeek / Qwen / Claude / 智谱 / 月之暗面 / OpenRouter 等任何 OpenAI 兼容代理。
> 性价比推荐：分类阶段用 `deepseek-ai/DeepSeek-V3.2`（任务简单、原生中文、约 GPT-4o 1/10 价格），翻译阶段用 `gpt-4o` 或 `claude-sonnet-4-6`（中文表达更精致）。

**Step 1 · 爬 + 二级分类**

```bash
python crawl_all_papers.py
```

从 ICML 官方虚拟站拉全部 6,567 篇接收论文 + abstract。然后：
- 论文若已带 ICML 官方 topic（如 `Deep Learning->Large Language Models`，约 22% 的论文）：直接拆出一级方向
- 论文若未带 topic（其余 78%）：调 LLM 把它归到 8 大类之一
- 每篇论文再调 LLM 在所属大类下打一个细分小类

> 想自己定制大类下的细分小类，改 `crawl_all_papers.py` 顶部的 `SUBCATEGORIES_BY_PRIMARY` 字典即可，每个大类下放任意数量小类。

**Step 2 · 中文六维度分析**

```bash
python translate_all_papers.py
```

会自动断点续跑，中断后重跑只翻译没翻完的。**这一步翻译质量直接影响阅读体验**，推荐用 `gpt-4o` 或 `claude-sonnet-4-6`。

**Step 3 · 三级分类（只对 11 个肥桶）**

```bash
python classify_third_level.py
```

只对二级 ≥150 篇的 11 个桶（如"大语言模型"、"多模态/VLM"）再切一刀三级，让导航不至于"翻 500 条"。三级清单在 `classify_third_level.py` 顶部的 `THIRD_LEVEL_BY_SUB` 字典里。

**Step 4 · 渲染网页**

```bash
python build_html_full.py    # 输出 index.html
```

---

四步全部支持断点续跑：中断后重跑会自动跳过已完成的论文。

---

## 📂 文件说明

| 文件 | 说明 |
| --- | --- |
| `index.html` | 静态网页（主入口，零依赖） |
| `ICML2026_all_papers.json` | 6,567 篇原始数据 + 一二三级（标题、作者、摘要、tier、URL …） |
| `ICML2026_all_papers_CN.json` | 在原始数据上叠加六维度中文分析 |
| `crawl_all_papers.py` | 爬取 ICML 虚拟站 + 一二级分类 |
| `translate_all_papers.py` | 调 LLM 生成中文六维度分析 |
| `classify_third_level.py` | 对 11 个肥桶再切三级分类 |
| `build_html_full.py` | 把 JSON 渲染成 HTML（含搜索 + 三级折叠目录 + Spotlight 筛选 + 回到顶部） |

---

## 🔌 数据来源

- 元数据：<https://icml.cc/static/virtual/data/icml-2026-orals-posters.json>
- Abstract：<https://icml.cc/static/virtual/data/icml-2026-abstracts.json>
- 网页入口：<https://icml.cc/virtual/2026/papers.html>

档次区分：
- `Accept (spotlight)` → ⭐ Spotlight（575 篇）
- `Accept (regular)` → Poster（5,992 篇）
- （ICML 2026 此刻尚未公布 Oral 名单；后续如有更新可重跑 Step 1 自动同步）

---

## ⚠️ 免责声明

- 中文分析由大语言模型基于英文 abstract 自动生成，**仅供快速浏览参考**，详细内容请以 ICML 论文页 / OpenReview 原文为准。
- 二级小类由 LLM 自动打标，可能存在错分。
- 数据快照时间见 `ICML2026_all_papers.json` 的 `meta.generated_at` 字段。

---

## 📜 License

MIT
