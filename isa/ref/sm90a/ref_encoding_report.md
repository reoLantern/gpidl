# ref-encoding.json 格式分析报告

- input: `/home/mmy/work/gpidl/isa/ref/sm90a/ref-encoding.json`
- instructions: 1505

## 阅读指南（先看这段）

- 这份报告的目标：把 `ref-encoding.json` 的“公共格式/字段语义/选项关系”解释清楚，方便你做进一步解析或生成代码。
- 最重要的概念：每条指令都是 **128-bit**，`ranges.ranges` 把 0..127 bit **完整切分**成若干字段；每个字段有 `type/start/length/...`。
- `start` 的含义：从 **最低有效位 (LSB)** 开始计数的 bit index；因此解析一个字段值就是：`value = (inst >> start) & ((1<<length)-1)`。
- `ranges.inst` 的含义：16 字节的 hex 字符串，按 **little-endian** 解释成 128-bit 整数后，再用上面的 `start/length` 取字段值。
- 如果你只想快速知道有哪些字段类型：直接跳到“`type` 包含哪些选项”。
- 如果你想看某条指令下各种选项怎么互动：用 `--per-instruction` 输出“逐指令摘要”。

## 快速例子（用一条“功能比较全”的指令说明结构）

- example key: `4014.LDGSTS_RI_RI_P`
- example disasm: `@P0 LDGSTS.E.BYPASS.EF.INVALID0 [R0+0x1], [R0.U32+0x100], P0 ;`
- 你可以把它理解为：`ranges.ranges` 定义了 bit-layout；`parsed` 给出语法层面的指令/操作数；`modifiers/flags/operand_*` 等字段共同决定 disasm 里会出现哪些 token。
- example field types: {'constant': 6, 'predicate': 1, 'operand': 5, 'operand_modifier': 1, 'modifier': 4, 'flag': 1, 'operand_flag': 1, 'stall': 1, 'y': 1, 'r-bar': 1, 'w-bar': 1, 'b-mask': 1, 'reuse': 1}

## 顶层结构（每条指令对象的字段）

- 顶层 JSON 是一个 dict：key 是类似 `528.IADD3_R_P_P_R_R_R` 的字符串；value 是该“指令变体”的结构描述。
- unique keysets: 1
- 1505x keys=['canonical_name', 'disasm', 'modifiers', 'opcode_modis', 'operand_interactions', 'operand_modifiers', 'parsed', 'ranges']

### 字段之间的关键关系

- `parsed.base_name`：指令基本名字（例如 `IADD3`）。
- `opcode_modis`：这条变体在“名字层面”额外附加到指令名的 token（也会体现在 `canonical_name` 里）。
- `canonical_name`：**严格等于** `parsed.base_name` + `opcode_modis`（用 `.` 连接）。
- 关系校验：`canonical_name == parsed.base_name + ('.' + '.'.join(opcode_modis) if opcode_modis else '')`
  - 1505/1505 OK

## ranges 字段的公共格式

- `ranges` 是一个对象：
  - `inst`: 一个 16B 的 hex（示例编码；常用于校验/展示默认值）。
  - `ranges`: 一个 list，每项都是一个字段描述（`type/start/length/...`）。
- 报告里的校验项解释：
  - `ranges.ranges` keyset：确认每个字段是否都长得像同一个 schema。
  - partition(0..127)：确认字段把 128-bit 覆盖得严丝合缝（无重叠、无空洞）。
  - constant vs inst：确认 `type=constant` 真的和 `ranges.inst` 的对应 bit 一致。

- `ranges` object keysets: {('inst', 'ranges'): 1505}
- `ranges.ranges` 每个字段是否符合示例格式（固定 7 个 key）？
  - EXPECTED keys = ['constant', 'group_id', 'length', 'name', 'operand_index', 'start', 'type']
  - observed unique keysets = 1
  - 33287x keys=['constant', 'group_id', 'length', 'name', 'operand_index', 'start', 'type']
- partition(0..127) checks: OK
- `ranges.inst` (16B little-endian hex) checks: OK
- `type=constant` vs inst bits checks: OK

- opcode-like 字段（`constant@start=0,length=12`）解释：
  - 大多数指令都有一个位于 bit[0..11] 的常量段，看起来像“主 opcode”。
  - 少数指令缺失这个字段（例如 NOP / BMOV 相关），说明它们的编码形式不同。
  - 另外：顶层 key 的数字前缀（例如 `551.`）并不保证等于该 12-bit 常量；它更像是这个数据集内部的编号/族标识。
- opcode-like 字段（`constant@start=0,length=12`）: 1500/1505 有该字段
  - missing examples: ['0.NOP', '2390.BMOV_SNOWFLAKE_I', '2902.BMOV_SNOWFLAKE_c[I][I]', '854.BMOV_SNOWFLAKE_R', '2902.BMOV_SNOWFLAKE_cx[UR][I]']

## `type` 包含哪些选项

- 下面列出的 `type` 是 `ranges.ranges` 里字段的分类。你可以把它理解为“这个 bitfield 在语义上表示什么”。

- unique `type` values: 13
- `constant`: 9905
- `operand`: 7361
- `modifier`: 2575
- `flag`: 1883
- `stall`: 1505
- `y`: 1505
- `b-mask`: 1505
- `reuse`: 1505
- `predicate`: 1504
- `operand_flag`: 1300
- `w-bar`: 1296
- `r-bar`: 1218
- `operand_modifier`: 225

## flags / operand_flags 的 name 取值（摘要）

- `type=flag`：指令级的 1-bit 开关（通常对应 disasm 里出现/消失一个 token）。
- `type=operand_flag`：操作数级的 1-bit 开关（通常对应某个 operand 的一元变换，如取反/取负/取绝对值）。

- `type=flag` unique names: 61
- `type=operand_flag` unique names: 6
- `type=flag` top names: [('NODEP', 189), ('FTZ', 142), ('SCR', 120), ('AOFFI', 108), ('LC', 96), ('SAT', 88), ('NDV', 88), ('E', 82), ('B', 67), ('RELU', 65), ('BF16_V2', 61), ('DC', 60), ('REGOFFSET', 60), ('FMZ', 55), ('F32', 40), ('ZFILL', 40), ('CL', 36), ('MS', 36), ('BF16', 33), ('TF32', 28), ('W', 26), ('NAN', 25), ('XORSIGN', 25), ('COARSE', 24), ('BA', 23)]
- `type=operand_flag` names: [('cNEG', 466), ('cNOT', 382), ('cABS', 272), ('cINV', 150), ('H1', 18), ('H0_NH1', 12)]

## modifiers / operand_modifiers 的结构（摘要）

- 这两块用于解释“枚举型字段”如何映射到 disasm 里的修饰符文本。
- 建议记住一个简单规则：
  - `type=modifier` 的第 0 个字段，对应 `modifiers[0]`；第 1 个字段对应 `modifiers[1]` ……（按字段出现顺序）。
  - `type=operand_modifier` 则按 `operand_index` 去 `operand_modifiers[str(operand_index)]` 查表。

- `modifiers`：list[table]，其中 table 是 `[[value:int, text:str], ...]`；每条指令里 `type=modifier` 的 bitfield 数量 == `len(modifiers)`（按出现顺序一一对应）。
- (modifier_fields, modifiers_tables) 分布：[((0, 0), 411), ((1, 1), 399), ((3, 3), 247), ((2, 2), 215), ((4, 4), 168), ((5, 5), 57), ((6, 6), 8)]
- modifiers 选项文本：single-token=18706, multi-token(含'.')=4106, empty=1521
- `operand_modifiers`：dict[str(operand_index) -> table]；并且 `type=operand_modifier` 的 operand_index 集合与 dict key 完全一致。
- operand_modifiers 选项文本：nonempty=601, empty=199

## 各 `type` 的字段约束与含义（推断）

- 这一节试图回答“每种 `type` 究竟代表什么？”以及“要看懂字段之间的关系，该怎么做？”。
- 下面两条是阅读后续内容的基础：
  - `start/length`：该字段在 128-bit 指令里的 bit 位置与宽度（start 从 LSB 开始计数）。
  - `ranges.ranges`：对每条指令都是一个 0..127 的完整分区，因此它就是该指令的完整 bit-layout。


### 字段约束（哪些字段会非空）

- `b-mask` (1505): operand_index=0/1505, group_id=0/1505, name=0/1505, constant=0/1505
- `constant` (9905): operand_index=0/9905, group_id=0/9905, name=0/9905, constant=9905/9905
- `flag` (1883): operand_index=0/1883, group_id=0/1883, name=1883/1883, constant=0/1883
- `modifier` (2575): operand_index=0/2575, group_id=2575/2575, name=0/2575, constant=0/2575
- `operand` (7361): operand_index=7361/7361, group_id=0/7361, name=0/7361, constant=0/7361
- `operand_flag` (1300): operand_index=1300/1300, group_id=0/1300, name=1300/1300, constant=0/1300
- `operand_modifier` (225): operand_index=225/225, group_id=0/225, name=0/225, constant=0/225
- `predicate` (1504): operand_index=0/1504, group_id=0/1504, name=0/1504, constant=0/1504
- `r-bar` (1218): operand_index=0/1218, group_id=0/1218, name=0/1218, constant=0/1218
- `reuse` (1505): operand_index=0/1505, group_id=0/1505, name=0/1505, constant=0/1505
- `stall` (1505): operand_index=0/1505, group_id=0/1505, name=0/1505, constant=0/1505
- `w-bar` (1296): operand_index=0/1296, group_id=0/1296, name=0/1296, constant=0/1296
- `y` (1505): operand_index=0/1505, group_id=0/1505, name=0/1505, constant=0/1505

### 语义总结（按 `type`）

- `constant`：固定比特段；`constant` 给出该段的数值（与 `ranges.inst` 对应）。
  - 常见用法：opcode、子操作选择、保留位/填充位。
- `operand`：操作数的编码比特段；`operand_index` 对应“展开后的 operand atom 索引”（由 `parsed.operands` 递归展开 `sub_operands` 得到）。
  - 同一个 operand 有时会分成多个不连续 bit 段（脚本在逐指令摘要里会把 segments 合并展示）。
- `modifier`：可枚举的“指令修饰符”编码段；值在 `modifiers` 表里映射为形如 `XXX.` 的文本。
  - 这些文本会变成 disasm 里的 `OP.MOD1.MOD2...` 形式；且一个选项文本可能自带多个 token（如 `F16x2.RN.`）。
  - 注意：`modifier` 与 `modifiers` 的匹配方式是“按 bitfield 出现顺序”一一对应；并且一个选项文本可能包含多个 token（如 `F16x2.RN.`）。
- `flag`：1-bit 指令级布尔开关；`name` 是开关名（如 `FTZ`、`SAT`）。
  - `name` 的语义需要结合 ISA/微架构文档才能完全解释；本报告主要说明它们如何出现在编码里。
- `operand_modifier`：可枚举的“操作数修饰符”编码段；查 `operand_modifiers[str(operand_index)]`。
- `operand_flag`：1-bit 操作数级布尔开关；典型 name 包括 `cNEG/cABS/cNOT/cINV` 等。
- `predicate`：谓词寄存器选择（4-bit）；与 `parsed.predicate`（如 `@P0`）相关。
- `stall/y/reuse/r-bar/w-bar/b-mask`：统一的调度/控制字段（通常在所有指令里位置固定，见下节）。

## 固定位字段（调度/控制）

- 这些字段在数据里表现为：几乎所有指令都包含，并且 `start/length` 完全固定。
- 它们更多描述调度/依赖/复用等控制信息，而不是指令本身的“操作数/功能”。

- `predicate` start/len 分布：[((12, 4), 1504)] (unique=1)
- `stall` start/len 分布：[((105, 4), 1505)] (unique=1)
- `y` start/len 分布：[((109, 1), 1505)] (unique=1)
- `r-bar` start/len 分布：[((110, 3), 1218)] (unique=1)
- `w-bar` start/len 分布：[((113, 3), 1296)] (unique=1)
- `b-mask` start/len 分布：[((116, 6), 1505)] (unique=1)
- `reuse` start/len 分布：[((122, 4), 1505)] (unique=1)

## operand_interactions 的含义与交互（推断）

- `operand_interactions`（若存在）按寄存器文件分类（`GPR/PRED/UGPR/UPRED`），列出每个 operand_atom 的读写属性：`[operand_index, 'R'|'W'|'RW', n]`。
- 其中 `n` 在数据里常见为 1/2/4（例如矩阵/向量指令可能一次读写多个寄存器）。
- 这为“每条指令下 operand 的角色（dst/src、读写宽度）”提供了直接信息，可与 `parsed.operands` 的类型一起理解。
- 实用建议：如果你要构建 dataflow/寄存器依赖分析，`operand_interactions` 往往比仅看 `parsed.operands` 更直接。
