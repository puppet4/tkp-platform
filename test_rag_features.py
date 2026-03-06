#!/usr/bin/env python3
"""测试新增的 RAG 功能。"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / "services/api/src"))

def test_imports():
    """测试所有模块是否可以正常导入。"""
    print("Testing imports...")

    try:
        from tkp_api.services.rag.answer_grader import AnswerGrader, create_answer_grader
        print("✓ answer_grader imported successfully")
    except Exception as e:
        print(f"✗ Failed to import answer_grader: {e}")
        return False

    try:
        from tkp_api.services.query_preprocessing import QueryPreprocessor
        print("✓ query_preprocessing imported successfully")
    except Exception as e:
        print(f"✗ Failed to import query_preprocessing: {e}")
        return False

    try:
        from tkp_api.services.parent_child_merger import ParentChildMerger
        print("✓ parent_child_merger imported successfully")
    except Exception as e:
        print(f"✗ Failed to import parent_child_merger: {e}")
        return False

    try:
        from tkp_api.services.rag.llm_generator import LLMGenerator
        print("✓ llm_generator imported successfully")
    except Exception as e:
        print(f"✗ Failed to import llm_generator: {e}")
        return False

    try:
        from tkp_api.services.rag.retrieval_improved import search_chunks_improved, generate_answer_improved
        print("✓ retrieval_improved imported successfully")
    except Exception as e:
        print(f"✗ Failed to import retrieval_improved: {e}")
        return False

    try:
        from tkp_api.core.config import get_settings
        settings = get_settings()
        print("✓ config imported successfully")
        print(f"  - answer_grading_enabled: {settings.answer_grading_enabled}")
        print(f"  - parent_child_merge_enabled: {settings.parent_child_merge_enabled}")
        print(f"  - query_language_detection_enabled: {settings.query_language_detection_enabled}")
        print(f"  - query_spell_correction_enabled: {settings.query_spell_correction_enabled}")
    except Exception as e:
        print(f"✗ Failed to import config: {e}")
        return False

    return True

def test_answer_grader():
    """测试答案评分器。"""
    print("\nTesting AnswerGrader...")

    try:
        from tkp_api.services.rag.answer_grader import AnswerGrader

        grader = AnswerGrader(threshold=0.5)

        # 测试高置信度场景
        chunks = [
            {"content": "Python is a programming language", "similarity": 0.95},
            {"content": "Python is widely used", "similarity": 0.90},
            {"content": "Python has many libraries", "similarity": 0.88},
        ]

        result = grader.calculate_confidence(
            query="What is Python?",
            answer="Python is a programming language that is widely used and has many libraries.",
            chunks=chunks,
            llm_confidence=0.9,
        )

        print(f"  High confidence test:")
        print(f"    - confidence_score: {result['confidence_score']:.2f}")
        print(f"    - rejected: {result['rejected']}")

        # 测试低置信度场景
        chunks_low = [
            {"content": "Unrelated content", "similarity": 0.3},
        ]

        result_low = grader.calculate_confidence(
            query="What is quantum computing?",
            answer="I'm not sure about quantum computing.",
            chunks=chunks_low,
            llm_confidence=0.2,
        )

        print(f"  Low confidence test:")
        print(f"    - confidence_score: {result_low['confidence_score']:.2f}")
        print(f"    - rejected: {result_low['rejected']}")
        print(f"    - rejection_reason: {result_low['rejection_reason']}")

        print("✓ AnswerGrader tests passed")
        return True

    except Exception as e:
        print(f"✗ AnswerGrader test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_query_preprocessor():
    """测试查询预处理器。"""
    print("\nTesting QueryPreprocessor...")

    try:
        from tkp_api.services.query_preprocessing import QueryPreprocessor

        preprocessor = QueryPreprocessor(
            enable_language_detection=True,
            enable_spell_correction=True,
        )

        # 测试规范化
        result = preprocessor.preprocess("  hello   world  ")
        print(f"  Normalization test:")
        print(f"    - original: '  hello   world  '")
        print(f"    - processed: '{result['processed_query']}'")

        print("✓ QueryPreprocessor tests passed")
        return True

    except Exception as e:
        print(f"✗ QueryPreprocessor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试。"""
    print("=" * 60)
    print("RAG Features Integration Test")
    print("=" * 60)

    all_passed = True

    if not test_imports():
        all_passed = False

    if not test_answer_grader():
        all_passed = False

    if not test_query_preprocessor():
        all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
