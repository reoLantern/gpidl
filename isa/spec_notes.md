# json 格式说明和文档约定

JSON（JavaScript Object Notation）是一种轻量、易读、跨语言的数据交换格式，常用于配置文件、接口请求与返回数据等场景。它的语法元素很少，但规则较严格，因此非常适合用来做“约定明确、机器易解析”的数据描述。

JSON 的整体结构可以理解为两类容器加若干基本值类型：花括号 `{}` 表示对象（object），用于表达“键名到值”的映射；方括号 `[]` 表示有序序列（标准术语为 array）。例如：

```json
{
  "user": {
    "id": 123,
    "name": "Ada"
  },
  "tags": ["dev", "ml"]
}
```

对象由若干成员组成，每个成员是“键名：值”。键名必须是字符串，因此一定写成双引号包裹的形式；成员之间用逗号分隔，键名与值之间用冒号分隔。与之对应，`[]` 中放的是按顺序排列的值，它们同样用逗号分隔：

```json
{
  "profile": {"email": "a@example.com", "active": true},
  "scores": [10, 20, 30]
}
```

JSON 允许的值类型只有六类：

* 对象：`{ ... }`
* 有序序列：`[ ... ]`
* 字符串：`"text"`
* 数字：`0`, `3.14`, `-2`
* 布尔：`true` / `false`
* 空值：`null`

文档中会把对象中的键统一称为“键名（key）”，对应内容称为“值（value）”。

此外，为了降低中文叙述的理解成本，本说明文档后续将把 `[]` 统一称为“列表”。这里的“列表”语义等同于标准术语 array：表示一个按顺序排列的值集合。

# GPU 架构定义

遵循 SIMT 编程模型。硬件将每 32 个 thread 组织成 1 个 warp，多个 warp 组成一个 thread block（CTA）。多个 CTA 组成一个 kernel launch。硬件调度单位为 warp，warp 内部的 thread 锁步同时执行同一条指令。

寄存器：

- VGPR: 每个 warp 有最多 255 个 VGPR（vector general-purpose register），编号为 R0 ~ R254，而 R255 表示 0，记为 RZ。每个 VGPR 为 warp 的每个 thread 各自存放 32-bit 数据，共 1024-bit。亦可理解成每个 thread 有最多 255 个私有的 32-bit 寄存器。

- SGPR: 每个 warp 有最多 63 个 SGPR（scalar general-purpose register），编号为 UR0 ~ UR62，而 UR63 表示 0，记为 URZ。每个 SGPR 为 warp 的所有 thread 共享存放 32-bit 数据，共 32-bit。

- Predicate Register: 每个 warp 有最多 7 个 predicate register，编号为 P0 ~ P6，而 P7 表示 True，记为 PT。每个 predicate register 为 warp 的所有 thread 各自存放 1-bit 数据，共 32-bit。亦可理解成每个 thread 有最多 7 个私有的 1-bit predicate 寄存器。

- Unified Predicate Register: 每个 warp 有最多 7 个 unified predicate register，编号为 UP0 ~ UP6，而 UP7 表示 True，记为 UPT。每个 unified predicate register 为 warp 的所有 thread 共享存放 1-bit 数据，共 1-bit。

- Barrier Register（Bx）: 控制流重汇合寄存器。每个 warp 有一组 B0、B1、…（数量待定，文献中通常描述为不少于 16 个），用于管理 warp 内控制流分歧后的 reconvergence。
  - 含义：Bx 中保存的是一组需要在未来重新汇合的线程掩码（reconvergence mask），以及与之关联的重汇合点信息。本质上类似 SIMT Stack 中的条目，但硬件直接支持 B 寄存器操作，编译器通过显式指令管理其内容。
  - 作用：在 Volta 及之后引入 Independent Thread Scheduling 后，warp 内线程可以暂时失去锁步执行。编译器通过 `BSSY Bx, target` 在分歧前记录当前活跃线程集合，并指定一个未来的汇合点；在该点用 `BSYNC Bx` 使这些线程重新汇合到同一执行路径。
  - 备注：当分歧嵌套过深、Bx 数量不足时，编译器可使用 `BMOV` 将 B 寄存器内容临时保存到普通寄存器中，再在需要时恢复。移动到普通寄存器的数据可以进一步进行 register spill。这是实验观察到的行为。

- Scoreboard Register（SBx）: 依赖计数器寄存器（software-managed scoreboard）。每个 warp 有 6 个 SB 寄存器，编号为 SB0 ~ SB5，每个通常可计数到 63。
  - 含义：SBx 本质上是“依赖未满足的计数器”，由编译器显式分配和维护，用来描述指令之间的 RAW / WAR / WAW 依赖关系，尤其是可变延迟操作（如内存访问、特殊功能单元指令）。
  - 作用：当某条 producer 指令发射时，相关的 SB 计数器增加；当结果就绪或依赖解除时，计数器减少。consumer 指令只有在其依赖的所有 SB 计数器归零后，或等待 SB 计数器小于某个阈值后，才能被调度发射。


# ISA spec 结构说明

此文件试图通过 jsonc（允许注释的 json）格式定义 GPU ISA 的指令集结构，而不直接定义其具体 encoding。职责是确认指令类型、操作数列表、modifier 等信息，同时添加必要的语义描述和注释说明；未来可考虑接入 Sail 这种 ISA Definition Language 来定义更精确的语义。此后，具体的 encoding 可以通过算法工具自动生成。

下方说明中未提到的字段一律禁止。

顶层对象必须包含以下键：gpidl_version、operand_width_bits、canonical_roles、global_oprnd_flag_defs、global_modifier_defs、instructions。

下列列表在其各自作用域内必须元素唯一：canonical_roles、inst_modifiers、fixed_modifiers、forms 的 key、以及 operands 的 name；同时，operands 的 name 不允许与任意上级 form 的 operands 重名。

键值对 gpidl_version 是版本号。必须是 JSON 字符串，内容格式不作限制。

键值对 operand_width_bits 表示操作数在指令中占据的位宽。其中的值必须是大于等于 0 的整数。

键值对 canonical_roles 是允许的操作数种类。

键值对 global_oprnd_flag_defs 是作用在某个操作数上的 modifier。
其内部，每个键值对是一个 modifier，包含以下信息：
- bits: 可选项。表示 modifier 在指令中的位宽。若未指定，则应根据 enum 推断，按照 enum 中最大值所需的位宽计算。
  - 若 bits 被指定，则需检查 enum 的取值范围：
    - enum 为 [] 时，元素数量不得超过 2^bits。
    - enum 为 {} 时，其值不得超过 bits 可表示的非负整数范围（即 <= 2^bits - 1）。
- enum: 必须项。表示 modifier 的枚举类型，定义了该 modifier 可取的值。可以是 [] 或 {}：
  - 前者 [] 表示枚举值列表，形如 `"enum": ["A", "B", "C"]`；
  - 后者 {} 强制指定了枚举值映射，形如 `"enum": { "A": 0, "B": 1, "C": 2 }`。其值必须是非负整数且不可重复。
- default: 可选项。modifier 的默认值，应为 enum 元素的 label。若指定，则指令的汇编格式中不显示该 modifier 的默认情况的名称。
- meaning: 可选项。modifier 的含义描述，可以是字符串（""）或字符串列表（["",""]）。

键值对 global_modifier_defs 是指令中可用的 modifier 定义。这一部分定义了一些指令公用的 modifier，以简化 jsonc 文件的编写。其余每个指令特有的 modifier 则在各自指令的定义中给出。
其内部，每个键值对是一个 modifier，包含以下信息：
- bits: 可选项。表示 modifier 在指令中的位宽。若未指定，则应根据 enum 推断。
- enum: 必须项。表示 modifier 的枚举类型，定义了该 modifier 可取的值。可以是 [] 或 {}，前者表示枚举值列表，后者强制指定了枚举值映射。
- default: 可选项。modifier 的默认值，应为 enum 元素的 label。若指定，则指令的汇编格式中不显示该 modifier 的默认情况的名称。
- can_apply_to_inst: 可选项。表示该 modifier 可作用的指令种类列表，对应 instruction 中的指令种类（即每个元素的 key）；若未指定则不做限制。
- meaning: 可选项。modifier 的含义描述，可以是字符串（""）或字符串列表（["",""]）。

键值对 instructions 定义了具体的指令集。其内部的每个键值对，key 是指令的名称，其 value object 描述指令的具体信息，包含以下字段：
- semantics: 可选项。指令的语义描述，包含以下字段（以下字段均为可选项）：
  - effect: 指令的效果描述，是一个字符串。
  - SASS: 指令在 NVIDIA SASS 中的参考名称，可以是字符串或字符串列表。并非一一对应。
  - notes: 指令的额外说明，是一个字符串列表。
- local_modifier_defs: 可选项。指令特有的 modifier 定义，格式同 global_modifier_defs。
- inst_modifiers: 可选项。指令使用的 modifier 列表。只能包含 global_modifier_defs 和本指令 local_modifier_defs 中定义的 modifier。
- fixed_modifiers: 可选项。modifier 列表，只能包含 global_modifier_defs 和本指令 local_modifier_defs 中定义的 modifier。且必须在同级的 forms 内部的每一个元素中，使用 fixed_modi_vals 指定值。用于将不同 form 以 modifier 的不同取值的形式区分开来。同一个 modifier 不允许同时出现在 inst_modifiers 和 fixed_modifiers 中。
  - 若某一层定义了 fixed_modifiers，则该层 forms 列表中的每一个元素必须提供 fixed_modi_vals（见下），但其键集合不需要覆盖 fixed_modifiers 的所有组合范围，取值必须为对应 modifier 的 enum label。
- forms: 必须项。指令的具体编码形式列表，代表同一个指令下的不同 encoding 形式，不同 form 的操作数数量、功能等可能不同。它的每个元素是一个 object，包含以下字段：
  - key: 必须项。某个 form 的唯一标识符，是一个字符串。
  - semantics: 可选项。该 form 的语义描述，格式同上级 instruction 的 semantics。
  - fixed_modi_vals: 当本指令有 fixed_modifiers 时，必须项，否则不应定义。用于指定本 form 中每个 fixed_modifiers 的取值。是一个 object，其键名为 fixed_modifiers 中的 modifier 名称，值为该 modifier 在本 form 中的取值。
  - local_modifier_defs: 可选项。该 form 特有的 modifier 定义，格式同 global_modifier_defs。
  - inst_modifiers: 可选项。该 form 使用的 modifier 列表。可以包含 global_modifier_defs、本指令 local_modifier_defs 以及本 form local_modifier_defs 中定义的 modifier。不能包含上级 inst_modifiers 和 fixed_modifiers 中的 modifier。
  - fixed_modifiers: 可选项。modifier 列表，只能包含 global_modifier_defs 和本指令 local_modifier_defs 中定义的 modifier。当且仅当本 form 还包含子 forms 列表时才可以定义。用于将不同子 form 以 modifier 的不同取值的形式区分开来。同一个 modifier 不允许同时出现在 inst_modifiers 和 fixed_modifiers 中，也不能包含上级 inst_modifiers 和 fixed_modifiers 中的 modifier。
  - operands: 可选项。该 form 的操作数列表；若不存在，则表示这一 form 层级没有操作数。其每个元素是一个 object，包含以下字段：
    - name: 必须项。操作数的名称，是一个字符串。同一 form 的不同 operands 不允许重名，亦不允许与上级 form 的 operands 重名。
    - role: 必须项。操作数的种类，对应 canonical_roles 中定义的操作数种类。
    - kind: 必须项。操作数的位宽类型，对应 operand_width_bits 中定义的类型。
    - oprnd_flag: 可选项。该操作数使用的 operand modifier 列表。只能包含 global_oprnd_flag_defs 中定义的 modifier。
    若本 form 不包含子 form 列表，则 operands 列表就是该 form 的最终操作数列表。否则，operands 是该 form 的基础操作数列表，最终操作数列表还需结合其子 form 列表中的 operands 一起确定。
  - forms: 可选项。该 form 的子 form 列表，代表同一个 form 下的不同 encoding 形式，不同子 form 的操作数数量、功能等可能不同。它的每个元素是一个 object，格式同上级 form 的 elements。由此可形成递归结构。
