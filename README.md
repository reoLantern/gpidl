# gpidl

`isa/spec_notes.md` 定义了 GPU ISA spec 的格式。

`isa/spec.jsonc` 是基于该格式编写的 GPU ISA spec。

`isa/validate_spec_format.py` 用于验证 spec.jsonc 的格式正确性。运行方式：

```bash
cd gpidl
python3 isa/validate_spec_format.py isa/spec.jsonc
```

`isa/encoding_synthesis_notes.md` 定义了基于 spec.jsonc 进行 encoding synthesis 的方法论。包括：
- encoding synthesis 的最终输出格式
- encoding synthesis 的算法说明
正在迭代中。各个版本脚本的使用方法见各个脚本开头的注释。
这些脚本都会生成 `encoding_synthesis_notes.md` 规定的 json 格式。

`isa/render_encoding_html.py` 脚本读取 encoding synthesis 生成的 json 文件，渲染成 html 格式。运行方式：

```bash
cd gpidl
python3 isa/render_encoding_html.py isa/encoding.v1.json -o isa/encoding.v1.html
```
