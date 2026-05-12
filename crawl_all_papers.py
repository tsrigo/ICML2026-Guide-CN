# -*- coding: utf-8 -*-
"""
ICML 2026 全量爬取 + 二级分类
==============================

数据源：ICML 官方虚拟会议站
  - https://icml.cc/static/virtual/data/icml-2026-orals-posters.json  （6,567 篇元数据）
  - https://icml.cc/static/virtual/data/icml-2026-abstracts.json      （摘要）

流水线：
  1. 拉两份 JSON，合并成统一 schema
  2. 大类：8 个 ICML 官方一级主题（Deep Learning / Applications / Social Aspects ...）
     -- 论文若已带 topic："Primary->Sub" 直接拆开复用
     -- 论文未带 topic：调 LLM 把它判到 8 大类之一
  3. 小类：每个大类下定义 5-15 个中文细分（见 SUBCATEGORIES_BY_PRIMARY），LLM 给每篇打小类
  4. 输出 ICML2026_all_papers.json

档次：根据 decision 字段
  - "Accept (spotlight)" → Spotlight (575 篇)
  - "Accept (regular)"   → Poster  (5,992 篇)
  目前数据里没有 Oral 标记；如果后续 ICML 公布 Oral，可以加一个 enrich 脚本补丁。

使用：
  pip install openai tqdm
  在 .env 里填 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL
  python crawl_all_papers.py

支持断点续跑：中断后重跑会跳过已分类的论文。
"""

import json
import os
import re
import ast
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---- 自动加载同目录下的 .env 文件 ----
def _load_dotenv():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip().strip("'\"")

_load_dotenv()

from openai import OpenAI
from tqdm import tqdm


# ============ 1. 基本配置 ============
ORALS_POSTERS_URL = "https://icml.cc/static/virtual/data/icml-2026-orals-posters.json"
ABSTRACTS_URL     = "https://icml.cc/static/virtual/data/icml-2026-abstracts.json"

OUTPUT_JSON = "ICML2026_all_papers.json"
DESCRIPTION = "ICML 2026 全部接收论文（中文导读 · 二级目录）"

# 本地缓存（避免每次重跑都下载 20MB）
CACHE_OP = Path(__file__).resolve().parent / "_raw_orals_posters.json"
CACHE_AB = Path(__file__).resolve().parent / "_raw_abstracts.json"

API_KEY  = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL    = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_WORKERS = 8
RESUME = True


# ============ 2. ICML 官方一级主题（大类）中英文对照 ============
PRIMARY_AREA_ZH = {
    "Deep Learning":              "深度学习",
    "Applications":               "应用",
    "Social Aspects":             "社会议题 (对齐/安全/公平等)",
    "General Machine Learning":   "通用机器学习",
    "Theory":                     "理论",
    "Reinforcement Learning":     "强化学习",
    "Optimization":               "优化",
    "Probabilistic Methods":      "概率方法",
}
PRIMARY_AREA_EN_LIST = list(PRIMARY_AREA_ZH.keys())  # 让 LLM 必选其一


# ============ 3. 二级分类清单：每个大类下的细分小类（中文 + 英文 hint）============
SUBCATEGORIES_BY_PRIMARY = {
    "深度学习": [
        {"name": "大语言模型 (LLM)",         "hint": "large language model, LLM, GPT, pretraining, instruction tuning, prompting"},
        {"name": "多模态/视觉-语言模型",     "hint": "multimodal, vision-language, VLM, MLLM, image-text"},
        {"name": "生成模型与扩散",           "hint": "generative model, diffusion, GAN, VAE, score-based, flow matching"},
        {"name": "基础模型",                 "hint": "foundation model, scaling laws, pretraining backbone"},
        {"name": "模型架构 (Transformer/MoE/SSM)", "hint": "architecture, transformer, attention, mixture-of-experts, MoE, state-space model, Mamba"},
        {"name": "图神经网络",               "hint": "graph neural network, GNN, message passing, graph transformer"},
        {"name": "自监督与表征学习",         "hint": "self-supervised, contrastive, masked image modeling, representation learning"},
        {"name": "训练算法与微调",           "hint": "training algorithm, fine-tuning, LoRA, distillation, optimizer for DL"},
        {"name": "鲁棒性与对抗",             "hint": "robustness, adversarial, out-of-distribution"},
        {"name": "时序与序列模型",           "hint": "sequential model, time series transformer, autoregressive"},
        {"name": "深度学习理论",             "hint": "deep learning theory, generalization in DL"},
        {"name": "其他",                     "hint": "其他深度学习相关"},
    ],
    "应用": [
        {"name": "计算机视觉",               "hint": "computer vision, image classification, detection, segmentation, 3D vision, video"},
        {"name": "自然语言/对话",            "hint": "natural language processing, NLP, speech, dialog"},
        {"name": "机器人",                   "hint": "robotics, manipulation, navigation, embodied AI"},
        {"name": "医学/健康",                "hint": "medical, healthcare, clinical, radiology, biomedical"},
        {"name": "化学/物理/地球科学",       "hint": "chemistry, physics, earth science, molecular, climate, material"},
        {"name": "生物 / 蛋白质 / 药物",     "hint": "biology, protein, drug discovery, genomics"},
        {"name": "神经科学",                 "hint": "neuroscience, cognitive science, brain, fMRI, EEG"},
        {"name": "时间序列",                 "hint": "time series forecasting, time series classification, anomaly detection"},
        {"name": "社会科学",                 "hint": "social science, economics, finance"},
        {"name": "能源",                     "hint": "energy, power, smart grid"},
        {"name": "其他应用",                 "hint": "其他不属于以上的应用"},
    ],
    "社会议题 (对齐/安全/公平等)": [
        {"name": "对齐 (Alignment)",         "hint": "alignment, RLHF, DPO, value alignment, preference learning"},
        {"name": "安全 (Safety)",            "hint": "safety, jailbreak, prompt injection, red-teaming"},
        {"name": "公平性",                   "hint": "fairness, bias, discrimination"},
        {"name": "隐私",                     "hint": "privacy, differential privacy, federated, membership inference"},
        {"name": "可解释性与透明度",         "hint": "interpretability, explainability, mechanistic, attribution"},
        {"name": "安全防御 (Security)",      "hint": "security, attack, defense, watermark, copyright"},
        {"name": "鲁棒性 (社会议题)",        "hint": "robustness in social aspects, distributional shift, audit"},
        {"name": "其他",                     "hint": "其他社会议题"},
    ],
    "通用机器学习": [
        {"name": "表征学习",                 "hint": "representation learning, embedding"},
        {"name": "迁移/元/多任务学习",       "hint": "transfer learning, meta learning, multitask, few-shot, lifelong"},
        {"name": "监督/半监督/无监督",       "hint": "supervised, semi-supervised, unsupervised learning"},
        {"name": "在线学习与 Bandits",       "hint": "online learning, bandits, active learning"},
        {"name": "评测",                     "hint": "evaluation, benchmark, eval methodology"},
        {"name": "因果性",                   "hint": "causality, causal inference, treatment effect"},
        {"name": "数据",                     "hint": "data curation, dataset, data-centric, data augmentation"},
        {"name": "聚类",                     "hint": "clustering, density estimation"},
        {"name": "时序/网络建模",            "hint": "sequential modeling, network modeling, time series modeling"},
        {"name": "核方法",                   "hint": "kernel method, RKHS"},
        {"name": "可扩展算法",               "hint": "scalable algorithm, large scale ML"},
        {"name": "方法论",                   "hint": "methodology, novel learning algorithm"},
        {"name": "硬件/软件",                "hint": "hardware, software, system, framework"},
        {"name": "其他",                     "hint": "其他通用 ML"},
    ],
    "理论": [
        {"name": "学习理论",                 "hint": "learning theory, PAC, generalization bounds, statistical learning"},
        {"name": "深度学习理论",             "hint": "deep learning theory, expressiveness, NTK, feature learning theory"},
        {"name": "优化理论",                 "hint": "optimization theory, convergence rates, complexity"},
        {"name": "在线学习与 Bandits 理论",  "hint": "online learning theory, bandits theory, regret bounds"},
        {"name": "博弈论",                   "hint": "game theory, equilibrium, mechanism design"},
        {"name": "概率方法理论",             "hint": "probabilistic methods theory, Bayesian theory"},
        {"name": "强化学习理论",             "hint": "RL theory, MDP analysis, regret in RL"},
        {"name": "域适应/迁移理论",          "hint": "domain adaptation theory, transfer theory"},
        {"name": "其他",                     "hint": "其他理论"},
    ],
    "强化学习": [
        {"name": "深度 RL",                  "hint": "deep RL, deep reinforcement learning"},
        {"name": "离线 RL",                  "hint": "offline RL, batch RL"},
        {"name": "多智能体",                 "hint": "multi-agent RL, MARL"},
        {"name": "探索/在线 RL",             "hint": "exploration, online RL, intrinsic reward"},
        {"name": "策略搜索",                 "hint": "policy search, policy gradient, actor-critic"},
        {"name": "规划",                     "hint": "planning, model-based RL"},
        {"name": "逆强化学习",               "hint": "inverse RL, IRL, reward learning, imitation"},
        {"name": "其他",                     "hint": "其他 RL"},
    ],
    "优化": [
        {"name": "凸优化",                   "hint": "convex optimization"},
        {"name": "非凸优化",                 "hint": "non-convex optimization"},
        {"name": "离散/组合优化",            "hint": "discrete, combinatorial optimization"},
        {"name": "大规模/并行/分布式",       "hint": "large scale, parallel, distributed optimization"},
        {"name": "随机优化",                 "hint": "stochastic optimization, SGD analysis"},
        {"name": "零阶/黑盒优化",            "hint": "zero-order, black-box, derivative-free"},
        {"name": "其他",                     "hint": "其他优化"},
    ],
    "概率方法": [
        {"name": "贝叶斯方法",               "hint": "Bayesian, posterior, prior"},
        {"name": "变分推断",                 "hint": "variational inference, ELBO, VI"},
        {"name": "MCMC/采样",                "hint": "MCMC, sampling, Langevin, HMC"},
        {"name": "高斯过程",                 "hint": "Gaussian process, GP"},
        {"name": "谱方法",                   "hint": "spectral methods, matrix decomposition"},
        {"name": "结构学习",                 "hint": "structure learning, graphical models"},
        {"name": "其他",                     "hint": "其他概率方法"},
    ],
}

# 兜底
DEFAULT_SUBCATEGORIES = [{"name": "其他", "hint": "无明确小类"}]


# ============ 4. 拉数据 ============
def _download(url, cache_path: Path, force=False):
    if cache_path.exists() and not force:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    print(f"  下载 {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    cache_path.write_bytes(data)
    return json.loads(data.decode("utf-8"))


def fetch_all_icml_papers():
    print("[1/3] 从 ICML 官方虚拟站拉数据...")
    op = _download(ORALS_POSTERS_URL, CACHE_OP)
    ab = _download(ABSTRACTS_URL, CACHE_AB)

    raw = op.get("results", op if isinstance(op, list) else [])
    abstracts = ab if isinstance(ab, dict) else {}
    # abstracts key 可能是 str(id)；ICML 数据是 str
    abs_map = {str(k): v for k, v in abstracts.items()}
    print(f"  共拉到 {len(raw)} 篇 + {len(abs_map)} 条摘要。")
    return raw, abs_map


def _safe_list(s):
    """authors / keywords 字段是 Python repr 字符串，需要安全 eval。"""
    if isinstance(s, list):
        return s
    if not s or s == "[]":
        return []
    try:
        v = ast.literal_eval(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _split_topic(t):
    """ICML topic 形如 'Deep Learning->Large Language Models'。"""
    if not t:
        return None, None
    parts = [p.strip() for p in t.split("->")]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return parts[0], None


def determine_tier(decision):
    d = (decision or "").lower()
    if "spotlight" in d:
        return "Spotlight"
    if "oral" in d:
        return "Oral"
    return "Poster"


def normalize_paper(r, abs_map):
    pid = str(r.get("id", ""))
    topic = r.get("topic") or ""
    primary_en, subtopic_en = _split_topic(topic)
    authors = _safe_list(r.get("authors", ""))
    author_names = [a.get("fullname", "") for a in authors if isinstance(a, dict)]
    abstract = abs_map.get(pid) or ""
    decision = r.get("decision") or ""
    vsurl = r.get("virtualsite_url") or ""
    if vsurl and not vsurl.startswith("http"):
        vsurl = "https://icml.cc" + vsurl
    return {
        "id": pid,
        "uid": r.get("uid", ""),
        "url": vsurl,                                    # ICML 虚拟站页面
        "paper_url": r.get("paper_url") or "",           # OpenReview / paper PDF
        "title": (r.get("name") or "").strip(),
        "authors": author_names,
        "primary_area_en": primary_en or "",
        "primary_area": PRIMARY_AREA_ZH.get(primary_en, "") if primary_en else "",
        "icml_subtopic_en": subtopic_en or "",           # ICML 官方 subtopic（仅作参考）
        "category": None,                                # 待 LLM 填的中文小类
        "keywords": [],                                  # ICML 官方接口无 keywords
        "tldr": "",                                      # ICML 官方接口无 TL;DR
        "abstract": abstract.strip(),
        "decision": decision,
        "tier": determine_tier(decision),
    }


# ============ 5. LLM 分类 ============
SYSTEM_PROMPT_PRIMARY = (
    "你是一位精通中英文的 AI 研究员。给定一篇论文和 ICML 官方 8 个一级研究方向，"
    "你需要选出最匹配的一个。严格只输出 JSON：{\"primary\": \"<English Name>\"}，"
    "不要写任何解释、Markdown、思考过程。"
)

SYSTEM_PROMPT_SUB = (
    "你是一位精通中英文的 AI 研究员。给定一篇论文和它所在大类下的小类清单，"
    "你需要选出最匹配的一个小类。严格只输出 JSON：{\"category\": \"<中文名>\"}，"
    "不要写任何解释、Markdown、思考过程。"
)


def build_primary_prompt(paper):
    lines = "\n".join(f"- {en}（{PRIMARY_AREA_ZH[en]}）" for en in PRIMARY_AREA_EN_LIST)
    icml_hint = ""
    if paper.get("icml_subtopic_en"):
        icml_hint = f"\n【ICML 官方 subtopic 提示】{paper['icml_subtopic_en']}\n"
    return f"""请把这篇 ICML 2026 论文判定到下列 8 个一级研究方向之一：

{lines}

规则：
1. 只能选上面 8 个英文名之一，一字不差。
2. 主要看论文的研究焦点，不被应用场景误导（例如医学图像里的对抗鲁棒性研究应归到 Deep Learning 或 Social Aspects，不一定归到 Applications）。

【论文标题】{paper['title']}
{icml_hint}
【Abstract】
{paper.get('abstract', '')[:2000]}

只输出 JSON：{{"primary": "<English Name>"}}"""


def build_sub_prompt(paper, subcats):
    cat_list = "\n".join(f"- {c['name']}：{c['hint']}" for c in subcats)
    fallback = subcats[-1]["name"]
    icml_hint = ""
    if paper.get("icml_subtopic_en"):
        icml_hint = f"\n【ICML 官方 subtopic 提示】{paper['icml_subtopic_en']}\n"
    return f"""这篇论文属于大类「{paper['primary_area']}」。请从下列小类中选**最匹配的一个**，输出 JSON：

{cat_list}

规则：
1. 只能从上面列表里选，名字一字不差。
2. 不到万不得已不要选 "{fallback}"。明显属于具体类别的，必须选具体类别。
3. 同时涉及多个时，选**研究焦点最集中**的那个。

【论文标题】{paper['title']}
{icml_hint}
【Abstract】
{paper.get('abstract', '')[:2000]}

只输出 JSON：{{"category": "<中文名>"}}"""


def _extract_text(resp):
    if isinstance(resp, str):
        return resp
    try:
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return str(resp)[:500]


def _parse_one(text, key, valid_names):
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and key in obj:
            cand = str(obj[key]).strip()
            if cand in valid_names:
                return cand
    except Exception:
        pass
    m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', raw)
    if m and m.group(1) in valid_names:
        return m.group(1)
    cleaned = re.sub(r"[\"'`*【】「」\s]", "", raw)
    for name in valid_names:
        if cleaned == re.sub(r"\s", "", name):
            return name
    real = [n for n in valid_names if n != "其他" and not n.endswith("其他")]
    hits = [n for n in real if n in raw]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return max(hits, key=len)
    for n in valid_names:
        if n in raw:
            return n
    return None


def _llm_call(client, system, user, max_tokens=200):
    kwargs = dict(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0,
    )
    try:
        return client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
    except Exception:
        return client.chat.completions.create(**kwargs)


def categorize_paper(client, paper):
    """返回 (id, primary_zh, sub_zh, error)。"""
    # ---- 1. 大类 ----
    primary_zh = paper.get("primary_area") or ""
    primary_en = paper.get("primary_area_en") or ""
    if not primary_zh:
        # 论文没填官方 topic，让 LLM 选
        try:
            resp = _llm_call(client, SYSTEM_PROMPT_PRIMARY,
                             build_primary_prompt(paper), max_tokens=80)
            text = _extract_text(resp)
            en = _parse_one(text, "primary", PRIMARY_AREA_EN_LIST)
            if en:
                primary_en = en
                primary_zh = PRIMARY_AREA_ZH[en]
            else:
                # 实在解析不出来，扔到"通用机器学习"做兜底
                primary_en = "General Machine Learning"
                primary_zh = PRIMARY_AREA_ZH[primary_en]
        except Exception as e:
            return paper["id"], "通用机器学习", "其他", f"primary api error: {e}"

    # ---- 2. 小类 ----
    subcats = SUBCATEGORIES_BY_PRIMARY.get(primary_zh, DEFAULT_SUBCATEGORIES)
    valid = [c["name"] for c in subcats]
    fallback = subcats[-1]["name"]
    paper2 = {**paper, "primary_area": primary_zh, "primary_area_en": primary_en}
    try:
        resp = _llm_call(client, SYSTEM_PROMPT_SUB, build_sub_prompt(paper2, subcats))
        text = _extract_text(resp)
        name = _parse_one(text, "category", valid)
        if name is None:
            return paper["id"], primary_zh, fallback, f"unparsed: {text[:100]}"
        return paper["id"], primary_zh, name, None
    except Exception as e:
        return paper["id"], primary_zh, fallback, f"sub api error: {e}"


# ============ 6. 主流程 ============
def save(papers, total_accepted, tier_counts):
    out = {
        "meta": {
            "source": "ICML 2026 official virtual site",
            "endpoints": {
                "orals_posters": ORALS_POSTERS_URL,
                "abstracts": ABSTRACTS_URL,
            },
            "total": len(papers),
            "total_accepted": total_accepted,
            "tier_counts": dict(tier_counts),
            "description": DESCRIPTION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "taxonomy": "two-level: ICML official primary topic → custom Chinese subcategory (LLM)",
            "fields": {
                "id": "ICML 论文唯一标识",
                "url": "ICML 虚拟站论文页",
                "paper_url": "OpenReview / 论文 PDF 链接",
                "title": "英文标题",
                "authors": "作者列表",
                "primary_area": "一级研究方向（中文，8 个之一）",
                "primary_area_en": "一级研究方向（英文）",
                "icml_subtopic_en": "ICML 官方 subtopic（英文，可能为空）",
                "category": "二级小类（中文，LLM 标）",
                "abstract": "完整 Abstract",
                "decision": "Accept (regular) / Accept (spotlight)",
                "tier": "Spotlight / Poster / Oral",
            },
        },
        "papers": papers,
    }
    Path(OUTPUT_JSON).write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    if API_KEY == "YOUR_API_KEY_HERE":
        raise SystemExit("❌ 请先在 .env 写 OPENAI_API_KEY")
    print(f"使用 LLM: {MODEL} @ {BASE_URL}  (key: {API_KEY[:8]}...)")

    # ---- 1. 拉数据 ----
    raw, abs_map = fetch_all_icml_papers()
    all_papers = [normalize_paper(r, abs_map) for r in raw]

    # 大类分布（基于 ICML 官方 topic，仅供参考）
    have_primary = sum(1 for p in all_papers if p["primary_area"])
    print(f"\n[2/3] 论文 topic 填写情况：{have_primary}/{len(all_papers)} 已填，剩余 {len(all_papers)-have_primary} 需 LLM 兜底。")
    tier_cnt = Counter(p["tier"] for p in all_papers)
    print(f"  档次分布：{dict(tier_cnt)}")

    # ---- 2. 续跑 ----
    done = {}
    if RESUME and Path(OUTPUT_JSON).exists():
        try:
            existing = json.loads(Path(OUTPUT_JSON).read_text(encoding="utf-8"))
            is_preview = bool(existing.get("meta", {}).get("preview"))
            if is_preview:
                print(f"\n[3/3] 检测到上次是无 LLM 预览版，已忽略所有 RESUME 数据，从头跑分类。")
            else:
                done = {p["id"]: p for p in existing.get("papers", []) if p.get("category")}
                if done:
                    print(f"\n[3/3] 已恢复 {len(done)} 篇已分类的论文。")
        except Exception:
            pass
    if not done:
        print("\n[3/3] 调用 LLM 给每篇论文分配 (大类, 小类)...")

    todo = [p for p in all_papers if p["id"] not in done]
    results = list(done.values())

    if todo:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        pbar = tqdm(total=len(todo), desc="分类中")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(categorize_paper, client, p): p for p in todo}
            for fut in as_completed(futures):
                pid, pri_zh, sub_zh, err = fut.result()
                paper = futures[fut]
                rec = {
                    **paper,
                    "primary_area": pri_zh,
                    "primary_area_en": paper.get("primary_area_en") or {v: k for k, v in PRIMARY_AREA_ZH.items()}.get(pri_zh, ""),
                    "category": sub_zh,
                }
                if err:
                    rec["category_error"] = err
                    tqdm.write(f"[警告] {pid}: {err[:120]}")
                results.append(rec)
                pbar.update(1)
                if len(results) % 100 == 0:
                    save(results, len(all_papers), tier_cnt)
        pbar.close()
    else:
        print("  无新论文需要分类。")

    # ---- 3. 排序：大类按论文数降序 ----
    primary_cnt = Counter(p["primary_area"] for p in results)
    primary_order = {k: i for i, (k, _) in enumerate(primary_cnt.most_common())}

    def sort_key(p):
        primary = p.get("primary_area", "")
        subcats = SUBCATEGORIES_BY_PRIMARY.get(primary, DEFAULT_SUBCATEGORIES)
        sub_order = {c["name"]: i for i, c in enumerate(subcats)}
        return (
            primary_order.get(primary, 999),
            sub_order.get(p.get("category", ""), 999),
            p["title"],
        )
    results.sort(key=sort_key)

    save(results, len(all_papers), tier_cnt)
    print(f"\n✅ 完成！共 {len(results)} 篇 → {OUTPUT_JSON}")

    # 最终分布
    print("\n二级目录分布:")
    by_primary = Counter(p["primary_area"] for p in results)
    for primary, _ in by_primary.most_common():
        n = by_primary[primary]
        print(f"\n📁 {primary} ({n})")
        sub_cnt = Counter(p["category"] for p in results if p["primary_area"] == primary)
        for sub, c in sub_cnt.most_common():
            print(f"    └─ {sub}: {c}")


if __name__ == "__main__":
    main()
