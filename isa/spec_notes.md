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

# ISA spec 结构说明

键值对 operand_width_bits 表示操作数在指令中占据的位宽。

键值对 canonical_roles 是允许的操作数种类。

键值对 global_oprnd_flag_defs 是作用在某个操作数上的 modifier。
其内部，每个键值对是一个 modifier，包含以下信息：
- bits: 可选项。表示 modifier 在指令中的位宽。若未指定，则应根据 enum 推断。
- enum: 必须项。表示 modifier 的枚举类型，定义了该 modifier 可取的值。可以是 [] 或 {}，前者表示枚举值列表，后者强制指定了枚举值映射。
- can_apply_to_roles: 必须项。表示该 modifier 可作用的操作数种类列表，对应 canonical_roles 中的操作数种类。
- default: 可选项。modifier 的默认值。若指定，则指令的汇编格式中不显示该 modifier 的默认情况的名称。
- meaning: 可选项。modifier 的含义描述，可以是字符串（""）或字符串列表（["",""]）。

键值对 global_modifier_defs 是指令中可用的 modifier 定义。这一部分定义了一些指令公用的 modifier，以简化 jsonc 文件的编写。其余每个指令特有的 modifier 则在各自指令的定义中给出。
其内部，每个键值对是一个 modifier，包含以下信息：
- bits: 可选项。表示 modifier 在指令中的位宽。若未指定，则应根据 enum 推断。
- enum: 必须项。表示 modifier 的枚举类型，定义了该 modifier 可取的值。可以是 [] 或 {}，前者表示枚举值列表，后者强制指定了枚举值映射。
- default: 可选项。modifier 的默认值。若指定，则指令的汇编格式中不显示该 modifier 的默认情况的名称。
- can_apply_to_inst: 可选项。表示该 modifier 可作用的指令种类列表，对应 instruction 中的指令种类；若未指定则不做限制。
- meaning: 可选项。modifier 的含义描述，可以是字符串（""）或字符串列表（["",""]）。

键值对 instructions 定义了具体的指令集。其内部的每个键值对，key 是指令的名称，其 value object 描述指令的具体信息，包含以下字段：
- semantics: 必须项。指令的语义描述，包含以下字段（以下字段均为可选项）：
  - effect: 指令的效果描述，是一个字符串。
  - SASS: 指令在 NVIDIA SASS 中的参考名称。并非一一对应。
  - notes: 指令的额外说明，是一个字符串列表。
- local_modifier_defs: 可选项。指令特有的 modifier 定义，格式同 modifier_defs。
- inst_modifiers: 可选项。指令使用的 modifier 列表。只能包含 global_modifier_defs 和本指令 local_modifier_defs 中定义的 modifier。
- fixed_modifiers: 可选项。modifier 列表，且必须在同级的 form 内部的每一个元素中，使用 fixed_modi_vals 指定值。用于将不同 form 以 modifier 的不同取值的形式区分开来。同一个 modifier 不允许同时出现在 inst_modifiers 和 fixed_modifiers 中。
- forms: 必须项。指令的具体编码形式列表，代表同一个指令下的不同 encoding 形式，不同 form 的操作数数量、功能等可能不同。它的每个元素是一个 object，包含以下字段：
  - key: 必须项。某个 form 的唯一标识符，是一个字符串。
  - fixed_modi_vals: 当本指令有 fixed_modifiers 时，必须项，否则不应定义。用于指定本 form 中每个 fixed_modifiers 的取值。是一个 object，其键名为 fixed_modifiers 中的 modifier 名称，值为该 modifier 在本 form 中的取值。
  - local_modifier_defs: 可选项。该 form 特有的 modifier 定义，格式同 modifier_defs。
  - inst_modifiers: 可选项。该 form 使用的 modifier 列表。可以包含 global_modifier_defs、本指令 local_modifier_defs 以及本 form local_modifier_defs 中定义的 modifier。不能包含上级 inst_modifiers 和 fixed_modifiers 中的 modifier。
  - fixed_modifiers: 可选项。modifier 列表。当且仅当本 form 还包含子 form 列表时才可以定义。用于将不同子 form 以 modifier 的不同取值的形式区分开来。同一个 modifier 不允许同时出现在 inst_modifiers 和 fixed_modifiers 中，也不能包含上级 inst_modifiers 和 fixed_modifiers 中的 modifier。
  - operands: 可选项。该 form 的操作数列表。其每个元素是一个 object，包含以下字段：
    - name: 必须项。操作数的名称，是一个字符串。
    - role: 必须项。操作数的种类，对应 canonical_roles 中定义的操作数种类。
    - kind: 必须项。操作数的位宽类型，对应 operand_width_bits 中定义的类型。
    - oprnd_flag: 可选项。该操作数使用的 operand modifier 列表。只能包含 global_oprnd_flag_defs 中定义的 modifier。
    若本 form 不包含子 form 列表，则 operands 列表就是该 form 的最终操作数列表。否则，operands 是该 form 的基础操作数列表，最终操作数列表还需结合其子 form 列表中的 operands 一起确定。
  - forms: 可选项。该 form 的子 form 列表，代表同一个 form 下的不同 encoding 形式，不同子 form 的操作数数量、功能等可能不同。它的每个元素是一个 object，格式同上级 form 的 elements。由此可形成递归结构。