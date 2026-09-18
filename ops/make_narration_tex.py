#!/usr/bin/env python3
"""把逐页中文旁白注入 main.tex，生成 main_with_narration.tex（页序与 PDF 物理页一一对应）。
用法: python make_narration_tex.py <main.tex> <out.tex>
"""
import sys
from pathlib import Path

NARRATIONS = [
    # 1 标题页
    "大家好，今天分享的是 NUS Show Lab 的 Paper2Video：把一篇研究论文自动变成一段有幻灯片、字幕、语音、光标和数字人讲者的学术演示视频。",
    # 2 目录
    "分享分九个部分：作者与动机、相关工作、方法、实验设计与结果、局限性、要点总结与参考文献，附录补充评测、效率与消融三类细节。",
    # 3 节：作者介绍
    "先看作者与团队。",
    # 4 作者介绍
    "一作 Zeyu Zhu 是 ShowLab 的一年级博士生，合作者 Kevin Qinghong Lin 现在是牛津大学的博士后，通讯作者 Mike Shou 是 Show Lab 的负责人，团队主线是多模态生成与 Agent。",
    # 5 节：研究背景与动机
    "接下来看这篇论文要解决的问题。",
    # 6 这篇论文在做什么
    "论文给出两样东西：PaperTalker 多智能体框架，以及 Paper2Video 基准。基准包含 101 篇论文，配作者录制的视频、幻灯片与讲者元数据；整套生成只要六万两千个 token、约四十八分钟、成本约零点零零一美元。",
    # 7 Fig 1
    "这张总览图概括了两个核心问题：左边是怎么从论文生成演示视频，右边是怎么评测一段演示视频。",
    # 8 节：相关工作
    "相关工作可以从三路来看。",
    # 9 相关工作
    "端到端方法比如 Wan2.2 和 Veo3 直接生成视频，文字容易模糊、时长过短；多智能体方法比如 PresentAgent 和 PPTAgent 版式容易溢出、也没有讲者。本文改成生成 Beamer 源码再做树搜索版式优化，并补齐字幕、光标与讲者。",
    # 10 节：方法
    "方法部分，四个 builder 解耦。",
    # 11 方法总览
    "任务定义是：给定论文、作者肖像和语音样本，合成幻灯片、逐句对齐的字幕与语音、讲者、光标四通道协同的视频。Slide Builder 直接生成 Beamer 源码，编译时收集诊断信息并做聚焦修复。",
    # 12 方法核心设计要素
    "Tree Search Visual Choice 先用规则生成版式邻域，先调图片缩放，再调字号，渲染后由 VLM 打分选优。光标假设句内静止、句间移动；幻灯片之间相互独立，因此可以逐页并行。",
    # 13 Fig 4
    "这是 PaperTalker 的总览：树搜索版式优化、GUI grounding 配合 WhisperX 的时空光标，以及逐页并行生成。",
    # 14 Fig 5
    "这是树搜索的流程，规则提案加 VLM 打分，选出最优候选。",
    # 15 节：实验设计
    "接着是实验设置与评测协议。",
    # 16 实验设计
    "基准是 101 篇论文，平均 28.7 页、13.3K 词、44.7 张图；视频平均 16 张幻灯片、六分十五秒。对比三类基线，VLM 用 GPT-4.1、VideoLLM 用 Gemini-2.5-Flash，推理用八张 A6000。",
    # 17 节：实验结果
    "下面看主结果。",
    # 18 主表
    "主表上，PaperTalker 的语音与内容相似度在所有基线里最高，Arena 胜率百分之十七；PresentQuiz 的细粒度与理解两项分别是零点八四二和零点九五一；IP Memory 达到百分之五十，明显高于 Veo3 的百分之三十一点三。",
    # 19 分析
    "值得注意的是，PaperTalker 的视频平均二百三十四秒，比人类作品的三百七十五秒更短，但 PresentQuiz 反而更高，说明信息密度是关键；去掉讲者与光标，Arena 会从百分之十七掉到百分之十五点二。",
    # 20 Fig 6
    "人类评估里，人类作品得分最高，PaperTalker 排第二，优于其他所有基线。",
    # 21 节：局限性
    "也要看到边界。",
    # 22 局限性
    "输入需要 LaTeX 源码、作者肖像和语音样本；完整流程要八张 GPU、约四十八分钟；评测依赖 VideoLLM 当裁判；光标假设在公式推导这类连续指向的场景下可能不够。",
    # 23 节：要点总结
    "最后总结要点。",
    # 24 要点总结
    "三条带走：Paper2Video 补上了演示视频评测的空白；PaperTalker 用生成 Beamer 加树搜索、时空光标、个性化语音与逐页并行；四项指标分别刻画保真、观感、信息覆盖与记忆。",
    # 25 节：参考文献
    "参考文献。",
    # 26 参考文献
    "主要参考本文，以及 PresentAgent、PPTAgent、Veo3、Wan2.2，还有 CAMEL、Hallo2、F5-TTS、UI-TARS、WhisperX 这些开源组件。",
    # 27 Q&A
    "我的分享到这里，谢谢观看，欢迎讨论。",
    # 28 附录分隔页
    "下面是附录部分。",
    # 29 附录 A
    "附录 A 给出基准统计和四项指标的取向。",
    # 30 图：评测指标
    "这张图系统展示了评测指标的设计视角，也就是从「与论文的关系」和「与人类视频的关系」两个方向去评测。",
    # 31 附录 B
    "效率和成本方面：PresentAgent 用二十四万一千个 token、三十九点五分钟；PaperTalker 只要六万两千个 token，逐页并行把耗时压到四十八点一分钟，成本约零点零零一美元。",
    # 32 附录 C
    "消融显示，光标把定位问答准确率从零点零八四提到零点六三三；树搜索主要提升设计分与连贯性。",
    # 33 图：树搜索前后
    "这是树搜索优化前后的幻灯片对比，上排是优化前，下排是优化后。",
    # 34 附录 D
    "从历史视角看：2024 年前后是幻灯片生成的时代；2025 年 Paper2Video 第一次把演示视频的多通道生成和评测基准一起提出来；再往后，论文传播正在走向全链路自动化。",
]


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    lines = src.read_text(encoding="utf-8").split("\n")
    queue = list(NARRATIONS)
    result = []

    def take() -> str:
        if not queue:
            raise SystemExit("narration queue exhausted (too many anchors)")
        return queue.pop(0)

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("% NARRATION:"):
            continue  # 幂等：丢掉旧标注
        if stripped.startswith("\\renewcommand{\\secblurb}"):
            result.append("% NARRATION: " + take())
        elif stripped.startswith("\\begin{frame}"):
            result.append("% NARRATION: " + take())
        result.append(line)

    if queue:
        raise SystemExit(f"unused narrations: {len(queue)}")
    out.write_text("\n".join(result), encoding="utf-8")
    print(f"wrote {out} with {len(NARRATIONS)} narrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
