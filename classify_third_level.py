# -*- coding: utf-8 -*-
"""
ICML 2026 三级分类（只针对 11 个肥二级桶 / 共 ~3198 篇）
=========================================================

读 ICML2026_all_papers.json + ICML2026_all_papers_CN.json，
对二级类别属于 THIRD_LEVEL_BY_SUB 的论文调 LLM 选三级，写回 subcategory 字段。
其他论文 subcategory 设为 None（保持两级即可）。

支持断点续跑。
"""

import json
import os
import re
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---- 加载 .env ----
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


INPUT_JSONS = [
    "ICML2026_all_papers.json",
    "ICML2026_all_papers_CN.json",
]

API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_WORKERS = 8
RESUME = True


# ============ 三级分类清单：(一级, 二级) → 三级 ============
THIRD_LEVEL_BY_SUB = {
    ("深度学习", "大语言模型 (LLM)"): [
        {"name": "RLHF / DPO / 偏好对齐",      "hint": "RLHF, DPO, IPO, KTO, ORPO, SimPO, preference optimization, RL for alignment, reward model"},
        {"name": "推理与思维链 (CoT)",          "hint": "chain-of-thought, reasoning, GRPO, math reasoning, logical reasoning, ToT, self-consistency, test-time compute"},
        {"name": "Agent 与工具使用",            "hint": "agent, tool use, function calling, GUI/web/mobile agent, computer use, multi-agent system"},
        {"name": "长上下文与检索增强 (RAG)",   "hint": "long context, context extension, RAG, retrieval-augmented generation, position embedding"},
        {"name": "效率/压缩/量化/推理加速",    "hint": "efficient inference, quantization, KV-cache, speculative decoding, distillation, sparsity, pruning of LLM"},
        {"name": "预训练与 Scaling",            "hint": "LLM pretraining, scaling law, data mixture, training data curation, continued pretraining"},
        {"name": "指令微调 (SFT) 与数据",      "hint": "instruction tuning, SFT, supervised fine-tuning, instruction data generation"},
        {"name": "评测与基准 (LLM)",            "hint": "LLM evaluation, benchmark, capability assessment, holistic eval"},
        {"name": "幻觉/事实性/可信",           "hint": "hallucination, factuality, faithfulness, truthful LLM"},
        {"name": "代码 LLM",                    "hint": "code LLM, code generation, code understanding, programming LLM"},
        {"name": "其他",                        "hint": "其他不属于以上的 LLM 话题"},
    ],
    ("深度学习", "多模态/视觉-语言模型"): [
        {"name": "VLM/MLLM 通用模型",           "hint": "vision-language model, multimodal LLM, MLLM, omni-model, unified multimodal architecture"},
        {"name": "视频理解 (VLM)",              "hint": "video understanding, long video, temporal reasoning, video QA, streaming video"},
        {"name": "文档/OCR/图表/GUI",          "hint": "OCR, document understanding, chart, table understanding, GUI/screen understanding"},
        {"name": "3D / 具身多模态",             "hint": "3D-language, 3D scene grounding, embodied multimodal, point cloud + language"},
        {"name": "视觉指令调优 / 训练方法",    "hint": "visual instruction tuning, multimodal SFT/RLHF, image-text training recipe"},
        {"name": "跨模态检索/生成/字幕",       "hint": "cross-modal retrieval, image-text matching, image captioning"},
        {"name": "评测与基准 (VLM)",            "hint": "VLM benchmark, multimodal eval, hallucination eval for VLM, visual reasoning bench"},
        {"name": "音频/语音多模态",             "hint": "audio-language, speech-language model, audio multimodal"},
        {"name": "其他",                        "hint": "其他多模态相关"},
    ],
    ("深度学习", "生成模型与扩散"): [
        {"name": "文本到图像 (T2I)",            "hint": "text-to-image, T2I generation, image synthesis from text"},
        {"name": "文本到视频 (T2V)",            "hint": "text-to-video, T2V, video generation, video diffusion"},
        {"name": "3D / 4D 生成",                "hint": "3D generation, 4D generation, mesh/NeRF/GS generation, scene generation"},
        {"name": "图像编辑与可控生成",          "hint": "image editing, inpainting, controllable generation, ControlNet, IP-Adapter"},
        {"name": "扩散理论与采样",              "hint": "diffusion theory, score-based, sampling, ODE/SDE solver, diffusion distillation"},
        {"name": "自回归 / 流匹配生成",         "hint": "autoregressive generation, flow matching, rectified flow, masked generation"},
        {"name": "音频/语音/音乐生成",          "hint": "audio generation, speech synthesis, music generation, TTS"},
        {"name": "分子/科学生成",               "hint": "molecular generation, protein generation, scientific generative model"},
        {"name": "其他",                        "hint": "其他生成相关"},
    ],
    ("深度学习", "训练算法与微调"): [
        {"name": "PEFT / LoRA / Adapter",       "hint": "parameter-efficient fine-tuning, LoRA, adapter, prefix tuning, prompt tuning"},
        {"name": "知识蒸馏",                    "hint": "knowledge distillation, teacher-student, KD, dark knowledge"},
        {"name": "持续/终身学习",              "hint": "continual learning, lifelong learning, catastrophic forgetting, incremental"},
        {"name": "迁移/元/少样本",              "hint": "transfer learning, meta learning, few-shot learning"},
        {"name": "正则化与稳定训练",            "hint": "regularization, dropout, batch norm, training stability, sharpness"},
        {"name": "数据选择/课程学习",           "hint": "data selection, curriculum learning, data pruning, importance sampling"},
        {"name": "优化器与学习率",              "hint": "optimizer design, learning rate schedule, Adam variants, second-order optim"},
        {"name": "其他",                        "hint": "其他训练算法"},
    ],
    ("深度学习", "模型架构 (Transformer/MoE/SSM)"): [
        {"name": "Transformer 变体",            "hint": "Transformer architecture, encoder-decoder, novel transformer variant"},
        {"name": "状态空间 (SSM/Mamba)",        "hint": "state space model, SSM, Mamba, S4, structured state space, linear recurrence"},
        {"name": "MoE / 稀疏专家",              "hint": "mixture of experts, MoE, sparse routing, expert parallelism"},
        {"name": "注意力机制",                  "hint": "attention mechanism, sparse/linear/efficient attention, flash attention"},
        {"name": "卷积/混合架构",               "hint": "convolution, hybrid architecture, ConvNet, conv+attention"},
        {"name": "新型递归/线性架构",           "hint": "RWKV, RetNet, novel recurrent architecture, linear RNN"},
        {"name": "其他",                        "hint": "其他架构"},
    ],
    ("强化学习", "策略搜索"): [
        {"name": "Actor-Critic / PPO 系列",     "hint": "actor-critic, PPO, A3C, on-policy gradient, TRPO"},
        {"name": "价值函数 / Q-learning",       "hint": "Q-learning, value function, DQN, value-based, TD learning"},
        {"name": "基于模型 RL",                 "hint": "model-based RL, world model, planning with learned model, Dreamer"},
        {"name": "偏好 / RLHF / 反馈 RL",       "hint": "preference-based RL, RL from human feedback, reward learning"},
        {"name": "策略优化理论",                "hint": "policy optimization theory, convergence analysis, regret bound"},
        {"name": "其他",                        "hint": "其他策略搜索"},
    ],
    ("应用", "计算机视觉"): [
        {"name": "检测与分割",                  "hint": "object detection, semantic/instance segmentation, panoptic, open-vocabulary detection"},
        {"name": "图像分类与识别",              "hint": "image classification, recognition, fine-grained, image retrieval"},
        {"name": "3D 视觉与重建",               "hint": "3D vision, point cloud, depth estimation, 3D reconstruction, NeRF, Gaussian splatting reconstruction"},
        {"name": "视频任务",                    "hint": "video classification, action recognition, video understanding (non-LLM), tracking"},
        {"name": "底层视觉 / 图像处理",         "hint": "low-level vision, super-resolution, denoising, restoration, dehazing"},
        {"name": "医学/科学影像",               "hint": "medical imaging, pathology, scientific image, radiology, microscopy"},
        {"name": "遥感与卫星",                  "hint": "remote sensing, satellite imagery, earth observation"},
        {"name": "人脸/姿态/人体",              "hint": "face recognition, pose estimation, person re-identification, human parsing"},
        {"name": "光流/跟踪/几何",              "hint": "optical flow, visual tracking, geometric vision, SfM, SLAM"},
        {"name": "CAD / 工程图 / 工业",         "hint": "parametric CAD, engineering drawing, mechanical, industrial vision"},
        {"name": "多模态生成与编辑",            "hint": "T2I generation as CV application, image editing, multimodal diffusion, MM-DiT, visual concept"},
        {"name": "视觉评测基准",                "hint": "visual benchmark, CV evaluation, structured generation eval, visual reasoning bench"},
        {"name": "代码/软件工程 Agent",         "hint": "code agent, software engineering agent, terminal agent, web agent benchmark, repo-level coding"},
        {"name": "安全/红队/审计",              "hint": "security agent, red team, cyber threat investigation, code vulnerability"},
        {"name": "图像/视频压缩",               "hint": "image compression, video compression, learned codec"},
        {"name": "其他",                        "hint": "其他 CV 应用"},
    ],
    ("强化学习", "探索/在线 RL"): [
        {"name": "探索策略",                    "hint": "exploration strategy, count-based, novelty search, UCB-style"},
        {"name": "内在奖励",                    "hint": "intrinsic reward, curiosity, RND, empowerment"},
        {"name": "Bandits",                     "hint": "multi-armed bandit, contextual bandit, linear bandit, regret minimization"},
        {"name": "在线学习",                    "hint": "online learning, online RL, adaptive learning, no-regret"},
        {"name": "其他",                        "hint": "其他探索/在线"},
    ],
    ("深度学习", "图神经网络"): [
        {"name": "节点/图分类",                 "hint": "node classification, graph classification, link prediction"},
        {"name": "图 Transformer",              "hint": "graph transformer, attention on graphs, positional encoding"},
        {"name": "等变 / 几何 GNN",             "hint": "equivariant GNN, geometric deep learning, E(3)-equivariant, message passing"},
        {"name": "异质图 / 知识图谱",           "hint": "heterogeneous graph, knowledge graph, relational"},
        {"name": "动态图 / 时序图",             "hint": "dynamic graph, temporal graph, streaming graph"},
        {"name": "图生成 / 分子",               "hint": "graph generation, molecular graph generation"},
        {"name": "GNN 理论与表达力",            "hint": "GNN theory, expressiveness, WL test, over-smoothing"},
        {"name": "其他",                        "hint": "其他 GNN"},
    ],
    ("优化", "大规模/并行/分布式"): [
        {"name": "分布式训练",                  "hint": "distributed training, data/model/pipeline parallel, ZeRO, tensor parallel"},
        {"name": "联邦学习",                    "hint": "federated learning, FedAvg, client heterogeneity, federated optimization"},
        {"name": "通信效率",                    "hint": "communication efficient, gradient compression, all-reduce optimization"},
        {"name": "大批量训练",                  "hint": "large batch training, scaling batch size, batch size schedule"},
        {"name": "异步/去中心化",               "hint": "asynchronous SGD, decentralized optimization, gossip"},
        {"name": "大模型推理加速",              "hint": "LLM inference acceleration, speculative decoding, KV-cache, batched serving, paged attention, scheduling"},
        {"name": "大模型训练稳定性/低精度",     "hint": "low-precision training, FP8, attention overflow, training stability for large models, 1-bit training"},
        {"name": "大规模优化器",                "hint": "large-scale optimizer, preconditioning, Shampoo, second-order optimizer, scalable matrix optim, Sophia"},
        {"name": "数据选择/数据高效",           "hint": "data selection, active learning for large model, sample utility, data pruning at scale"},
        {"name": "模型合并/集成",               "hint": "model merging, LoRA merging, multi-task model merging, weight averaging at scale"},
        {"name": "测试时计算/推理调度",         "hint": "test-time compute scaling, adaptive inference, inference budget"},
        {"name": "稀疏化/MoE 训练",             "hint": "sparsity in large-scale training, MoE training efficiency, sparse expert"},
        {"name": "显存/内存优化",               "hint": "memory-efficient training, activation checkpointing, gradient checkpointing, offloading"},
        {"name": "其他",                        "hint": "其他大规模优化"},
    ],
    ("深度学习", "自监督与表征学习"): [
        {"name": "对比学习",                    "hint": "contrastive learning, SimCLR, CLIP, InfoNCE, NT-Xent"},
        {"name": "掩码建模",                    "hint": "masked image modeling, MAE, BEiT, masked language model"},
        {"name": "跨模态预训练",                "hint": "cross-modal pretraining, vision-language pretraining"},
        {"name": "表征分析与探针",              "hint": "representation analysis, probing, feature analysis, neural collapse"},
        {"name": "音频/视频自监督",             "hint": "audio SSL, video SSL, multimodal SSL"},
        {"name": "其他",                        "hint": "其他自监督"},
    ],
}


SYSTEM_PROMPT = (
    "你是一位精通中英文的 AI 研究员。给定一篇论文和它已被归属的二级类别下的三级小类清单，"
    "选出最匹配的一个三级小类。严格只输出 JSON：{\"subcategory\": \"<中文名>\"}，"
    "不要任何解释、Markdown、思考过程。"
)


def build_prompt(paper, subs):
    cat_list = "\n".join(f"- {s['name']}：{s['hint']}" for s in subs)
    keywords = "、".join(paper.get("keywords", []) or [])
    fallback = subs[-1]["name"]
    return f"""这篇论文已被归类为「{paper['primary_area']} → {paper['category']}」。从下列三级小类中选**最匹配的一个**，输出 JSON：

{cat_list}

规则：
1. 只能从上面列表选，名字一字不差。
2. 不到万不得已不要选 "{fallback}"。明显属于具体类别的，必须选具体类别。
3. 同时涉及多个时，选**研究焦点最集中**的那个。

【论文标题】{paper['title']}
【关键词】{keywords}
【Abstract】
{(paper.get('abstract', '') or '')[:2500]}

只输出 JSON：{{"subcategory": "<中文名>"}}"""


def _parse(text, valid_names):
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "subcategory" in obj:
            cand = str(obj["subcategory"]).strip()
            if cand in valid_names:
                return cand
    except Exception:
        pass
    m = re.search(r'"subcategory"\s*:\s*"([^"]+)"', raw)
    if m and m.group(1) in valid_names:
        return m.group(1)
    real = [n for n in valid_names if n != "其他"]
    hits = [n for n in real if n in raw]
    if len(hits) == 1:
        return hits[0]
    if hits:
        return max(hits, key=len)
    for n in valid_names:
        if n in raw:
            return n
    return None


def classify(client, paper):
    key = (paper["primary_area"], paper["category"])
    subs = THIRD_LEVEL_BY_SUB[key]
    valid = [s["name"] for s in subs]
    fallback = subs[-1]["name"]
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(paper, subs)},
            ],
            max_tokens=120,
            temperature=0,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
    except Exception as e:
        return paper["id"], fallback, f"api: {str(e)[:80]}"
    name = _parse(text, valid)
    if name is None:
        return paper["id"], fallback, f"unparsed: {text[:80]}"
    return paper["id"], name, None


def main():
    if API_KEY == "YOUR_API_KEY_HERE":
        raise SystemExit("❌ 请先在 .env 写 OPENAI_API_KEY")
    print(f"使用 LLM: {MODEL} @ {BASE_URL}")

    # 读主 JSON
    data = json.loads(Path(INPUT_JSONS[0]).read_text(encoding="utf-8"))
    papers = data["papers"]

    # 1. 找出所有"在肥桶里、还没分三级"的论文
    todo = []
    fat_bucket_total = 0
    done_map = {}
    for p in papers:
        key = (p["primary_area"], p["category"])
        if key in THIRD_LEVEL_BY_SUB:
            fat_bucket_total += 1
            if RESUME and p.get("subcategory"):
                done_map[p["id"]] = p["subcategory"]
            else:
                todo.append(p)
    print(f"肥桶论文总数: {fat_bucket_total}")
    print(f"已分三级(续跑): {len(done_map)}")
    print(f"待分三级: {len(todo)}\n")

    # 2. 跑 LLM
    new_sub = {}
    if todo:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        pbar = tqdm(total=len(todo), desc="三级分类")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(classify, client, p): p for p in todo}
            for fut in as_completed(futs):
                pid, sub, err = fut.result()
                new_sub[pid] = sub
                if err:
                    tqdm.write(f"[警告] {pid}: {err}")
                pbar.update(1)
                # 每 200 篇落一次盘
                if len(new_sub) % 200 == 0:
                    _persist(new_sub | done_map)
        pbar.close()

    # 3. 把 subcategory 字段写回两个 JSON
    final = new_sub | done_map
    _persist(final)

    # 4. 最终统计
    print(f"\n✅ 完成。三级分类 {len(final)} 篇\n")
    data = json.loads(Path(INPUT_JSONS[0]).read_text(encoding="utf-8"))
    by_pri_sub = {}
    for p in data["papers"]:
        if (p["primary_area"], p["category"]) in THIRD_LEVEL_BY_SUB:
            k = (p["primary_area"], p["category"])
            by_pri_sub.setdefault(k, []).append(p.get("subcategory") or "(未分)")
    for (pri, sub), lst in sorted(by_pri_sub.items(), key=lambda kv: -len(kv[1])):
        print(f"\n📁 {pri} → {sub} ({len(lst)})")
        for n, c in Counter(lst).most_common():
            print(f"    └─ {n}: {c}")


def _persist(id_to_sub):
    """把 subcategory 字段写回所有 JSON 文件"""
    for fp in INPUT_JSONS:
        path = Path(fp)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for p in data["papers"]:
            key = (p["primary_area"], p["category"])
            if key in THIRD_LEVEL_BY_SUB:
                if p["id"] in id_to_sub:
                    p["subcategory"] = id_to_sub[p["id"]]
            else:
                p["subcategory"] = None  # 非肥桶显式设 None
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
