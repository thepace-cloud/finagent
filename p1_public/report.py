"""Build a reproducible local report without changing held-out scores."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
dev=json.loads((ROOT/"results/dev.json").read_text(encoding="utf-8"))
test=json.loads((ROOT/"results/test.json").read_text(encoding="utf-8"))
freeze=json.loads((ROOT/"selection.json").read_text(encoding="utf-8"))
assert all(sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in freeze["hashes"].items()), "Frozen implementation/data changed"
sources=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
cases=json.loads((ROOT/"cases_v2.json").read_text(encoding="utf-8"))
lines=["# FinAgent 公开语料多证据升级：实验交付", "", "日期：2026-10-24", "",
       "## 完成内容", "",
       "采集12份中国银行官方产品说明，保存原始HTML、文本、来源URL、抓取时间、内容哈希、产品ID和段落定位。网页没有物理页码，因此page=null。URL内的归档日期不冒充已确认的发布日期；未核实的发布时间为null。", "",
       "建立66题：单条款、多条款、产品比较、缺参、无答案、干扰各10题，另有6题确定性月供计算。30题开发、36题保留测试；无训练集。同一group不跨分区。相关任务仍共享来源文档与部分事实，不构成跨文档域外泛化测试。题目由AI编写和核对来源，未声称人工标注。", "",
       "核心机制为按产品与问题维度拆解、分支检索、去重合并。拆解保留原问题的客户类别、币种及上限等限定；词面检索使用全语料IDF，避免极小产品子集扭曲词项权重。基线与候选同样使用最多6个事实段落、同一个嵌入模型和生成模型。", "",
       "标题只作为事实段落的上下文，不单独占用证据预算。此预处理同时应用于基线和候选。月供使用代码计算，缺本金/合同利率/期限时先追问。计算工具是候选端附加能力，故总体字段通过率增量不能全部归因于检索机制。", "",
       "## 实测结果", "", "| 范围 | 指标 | 基线 | 候选 |", "|---|---|---:|---:|"]
for label,data in (("开发",dev),("保留",test)):
    a,b=data["summary"]["baseline"],data["summary"]["decomposed"]
    lines.extend([f"| {label} | 必要证据全部覆盖@6 | {a['evidence_complete']}/{a['retrieval_tasks']} | {b['evidence_complete']}/{b['retrieval_tasks']} |",
                  f"| {label} | 字段/状态/引文自动检查 | {a['automated_pass']}/{a['tasks']} | {b['automated_pass']}/{b['tasks']} |",
                  f"| {label} | MRR（首个必要证据） | {a['mrr']:.4f} | {b['mrr']:.4f} |"])
lines.extend(["", "MRR不能衡量多证据是否找全。保留集MRR小幅下降，完整覆盖提高；应同时看两个指标，不宣称所有指标均改善。无答案、缺参、纯计算题不纳入证据覆盖分母。", "",
              "生成模型：deepseek-chat，temperature=0；嵌入模型沿用本机pmml12。每种设置单次生成，没有多次独立训练或多随机种子统计。所有计分设置API错误为0。", "",
              "## 正确证据诊断与评分审计", "",
              f"Oracle直接给gold证据，保留集自动检查为{test['summary']['oracle']['automated_pass']}/36。它只是诊断，不是可部署策略，也没有使用候选的计算工具，因此不能把它当作包含工具的性能上限。",
              "",
              "- q25：答案正确保留了国家助学贷款‘学制剩余年限加15年、最长22年’的条件，评分器却因字段同时出现15和22而判错。属于自动评分假阴性。",
              "- q44：候选说明不存在统一固定利率，并引用差异化定价原文；标签只接受insufficient，未容纳有证据的前提纠正。属于标签/状态协议争议。",
              "- 以上两项在保留题揭晓后发现；原始34/36保持不改，未据此调参、改标签或改称36/36。它们也不能证明系统已无其他语义错误。",
              "- 开发阶段发现并修复金额单位、上限限定表达、numeric JSON值导致的格式假阴性；保留集前冻结了评分代码。最早结果和中间候选结果保存在results中。",
              "",
              "## 接口与验证", "",
              "独立FastAPI模块提供GET /health和POST /answer；不覆盖原V5服务或旧语料。返回字段、引文、原文位置、来源URL与检索计划。引用来源必须在本次证据内，引文必须逐字出现；额外检查产品归属和数字/金额是否在引文中。此守卫不能替代完整语义蕴含判断。",
              "",
              "12项行为/API守卫测试通过。真实ASGI lifespan + 本机嵌入模型 + 实际生成API的3次集成请求通过，包含跨产品额度比较、缺利率追问和月供计算。未进行公网部署、负载测试或外部用户验收。",
              "",
              "旧18题也已使用原三份演示语料和原策略实跑：检索13/16，检索达标题的引用白名单13/13，拒答关键词1/2。g04实际明确说明资料没有信用卡信息、不能准确答复，但其‘没法依据现有资料’措辞未命中旧拒答关键词，造成假阴性。原分数保留；引用通过也不能证明整段回答语义正确。",
              "",
              "在本目录使用现有venv运行：", "", "```powershell",
              "& '..\\..\\..\\venv\\Scripts\\python.exe' -m unittest test_public test_api -v",
              "& '..\\..\\..\\venv\\Scripts\\python.exe' -m uvicorn app:app --host 127.0.0.1 --port 8001",
              "```", "",
              "DEEPSEEK_API_KEY、DEEPSEEK_MODEL沿用父项目配置；不把.env或模型权重放入交付包。重复运行评测会使用已存响应缓存，不能算一次新的独立复跑。测试集已揭晓，后续改方法需新保留题。",
              "", "## 已知范围与后续使用", "",
              "12份资料来自同一家银行，包含近似产品条款，覆盖面有限。快照中部分页面归档较早、发布时间未确认，不能据此承诺当前办理条件。原18题在原三份演示语料上单独保留回归，分母和口径与新语料实验不同。",
              "",
              "该迭代可作为用户个人项目成果，代码由AI辅助实现。简历可描述数据、机制和实测结果，不写‘独立手写全部代码’或‘人工标注66题’。没有证据支持对大厂过筛率作保证。",
              "", "## 来源目录", ""])
for s in sources:
    lines.append(f"- [{s['title']}]({s['source_url']})：ID `{s['id']}`；抓取 {s['retrieved_at']}；SHA-256 `{s['sha256']}`。")
(ROOT/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
print("report built; frozen implementation verified")
print(dict(Counter(c['split'] for c in cases)))
