我们在 spec.jsonc 定义的指令语义的基础上，进行 encoding synthesis，生成各个指令的具体二进制 encoding 形式。

这项工作预计将迭代形成多种版本的指令 encoding。

# 最终 encoding 格式说明

encoding synthesis 的输出为一个 JSON 文件，用于描述“每个（instruction, form-path）叶子节点”的指令比特布局（bit layout）。该文件只描述：每一段 bit range 的含义、位宽、起始 bit、以及是否为常量。

最终的 ISA 规范，会同时参考 spec.jsonc 的语义，和脚本生成的 encoding 布局，从而完整定义每条指令的语义和编码。

约定：bit 0 为最低位；`start` 从 LSB 开始计数。

## 顶层结构

- `meta`: 元信息
  - `encoding_version`: 整数版本号
  - `statistics`: 一些统计信息，每个版本可能不同
- `encodings`: 一个 object，key 为 encoding 的唯一标识符，value 为该 encoding 的布局描述。

## `encodings` 的 key（唯一标识符）

使用 `"<inst_name>.<form_key0>[.<form_key1>...]"` 的格式（form 的 `key` 以树路径顺序连接）。如果某条指令只有一层 forms，则形如 `fadd.v_vv`；若出现嵌套 forms，则形如 `foo.a.b.c`。

## 单条 encoding value 的结构

- `instruction`: 指令名（与 spec 的 `instructions` key 一致）
- `form_path`: form 的 `key` 列表（从根到叶；若该指令只有一层 form，则只有一个元素）
- `ranges`: bit range 列表，每个元素描述一段连续位区间：
  - `type`: `constant` / `operand` / `oprnd_flag` / `modifier` / `reserved`
  - `start`: 起始 bit（LSB=0）
  - `length`: 位宽
  - `name`: 字段名。同一 encoding 的不同 bit range 不允许重名（除 null 外）。对于不同 `type`，`name` 的取值如下:
    - `constant`: null
    - `operand`: 操作数名称，与 spec 中 operands 的 `name` 一致。
    - `oprnd_flag`: 操作数修饰符名称，与 spec 中 `oprnd_flag` 的名称一致，且通过 `oprnd_idx` 指向对应操作数。
    - `modifier`: 指令修饰符名称，与 spec 中 modifier 的名称一致。
    - `reserved`: null
  - `constant`: 常量值，以十进制记录。仅当该字段的 `type` 为 `constant` 时出现；否则为 null。
  - `oprnd_idx`: 仅对 `oprnd_flag` 有效，指向该 encoding 中对应的 `operand` 的 `name`；其余 `type` 为 null。

# 版本迭代

## Version 1

完全按照 spec.jsonc 的 instructions - forms 树结构，依次为每一层 instruction 和 form 分配固定的 bitfield，从而生成最终的指令 encoding。

指令位宽固定为 128 bit。

算法如下：

分为 2 passes。

### pass 1：统计 opcode bitfield 大小

首先，统计 instructions 的数量 N_inst，以及每个 instruction 下每一级 forms 的最大数量 N_form_max_i，其中 i = 0, 1, ... 表示某一层 form / 子 form。

对于 N_inst 和 N_form_max_i (i = 0, 1, ...)，分别计算其二进制编码所需的最小位宽 bits_inst、bits_form_i。

将 bits_inst 分配给 instruction opcode field，将 bits_form_i 分配给第 i 层 form opcode field。这就确定了 opcode。

### pass 2：为每条 encoding 分配 bitfield

由于每条 encoding 对应了树形结构中的一个叶子节点，是 terminal 节点，因此可以唯一确定其 instruction 和 form_path。

按照 spec.jsonc 中 instructions 的顺序，为 instruction 分配 opcode bits，从 0 开始。

然后，为每条 instruction 下的 forms，按照 form_path 的顺序，为每一级 form 分配 opcode bits，从 0 开始。

为每个 encoding 分配完 opcode bits 后，剩余的 bit 位宽即为 operand 和 modifier bits。

对每个 form 的 operand、modifier 不做任何编码位置优化、重排，将它们依次编码在指令的剩余 bit 位中。具体顺序是：
- 所有 operands，按照 global - local 的顺序。
- 所有 oprnd_flags，按照对应 operands 的顺序。
- 所有 inst_modifiers，按照 global - local 的顺序。

每条 encoding 的剩余位宽用 `reserved=0` 填充。

脚本会输出最终的 encoding JSON 文件。

同时，在 `meta.statistics` 中输出统计信息：
- instructions 和 每一级 forms 的最大有效数量、对应的 opcode bits。