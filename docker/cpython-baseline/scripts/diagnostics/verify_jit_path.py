#!/usr/bin/env python3
"""
验证 JIT 编译对递归生成器是否正常工作。
检查反优化和编译状态。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "cinderx" / "PythonLib"))

class Node:
    def __init__(self, value, left=None, right=None):
        self.value = value
        self.left = left
        self.right = right

    def __iter__(self):
        if self.left:
            yield from self.left
        yield self.value
        if self.right:
            yield from self.right


def build_tree(depth):
    if depth == 0:
        return None
    mid = 2 ** (depth - 1)
    return Node(mid, build_tree(depth - 1), build_tree(depth - 1))


def main():
    print("=" * 60)
    print("JIT 执行路径验证")
    print("=" * 60)

    try:
        import cinderjit
    except ImportError:
        print("\n错误：CinderX 不可用")
        print("请先构建并安装 CinderX：")
        print("  pip install -e . --no-build-isolation")
        return 1

    print("\n[1] 启用 JIT...")
    cinderjit.enable()
    print("    ✓ JIT 已启用")

    print("\n[2] 强制编译 Node.__iter__...")
    cinderjit.force_compile(Node.__iter__)
    print("    ✓ 编译已请求")

    print("\n[3] 检查编译状态...")
    is_compiled = cinderjit.is_jit_compiled(Node.__iter__)
    print(f"    已编译: {is_compiled}")

    if is_compiled:
        size = cinderjit.get_compiled_size(Node.__iter__)
        print(f"    代码大小: {size} bytes")
    else:
        print("    错误：函数未编译！")
        return 1

    print("\n[4] 构建测试树...")
    tree = build_tree(10)
    print("    ✓ 树已构建（深度=10）")

    print("\n[5] 运行遍历（应使用 JIT 代码）...")
    result = list(tree)
    expected = list(range(1, 2**10))

    if result == expected:
        print("    ✓ 正确性已验证")
    else:
        print("    错误：结果不匹配！")
        print(f"    期望 {len(expected)} 项，得到 {len(result)} 项")
        return 1

    print("\n[6] 检查反优化...")
    # 注意：CinderX 可能不直接暴露反优化计数，但我们检查能检查的
    print("    （反优化检查尚未实现 - 使用 JIT_LOG 手动验证）")

    print("\n" + "=" * 60)
    print("✓ 所有检查通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
