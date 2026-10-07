from types import SimpleNamespace
import numpy as np
import torch
from medrag.retrieval.onnx_reranker import OnnxReranker


def test_onnx_predict_matches_tokenization_and_preserves_order():
    model = OnnxReranker.__new__(OnnxReranker)
    model.max_length = 512
    model.activation = torch.nn.Sigmoid()
    def tokenize(left, right, **kwargs):
        assert left == ["query", "query"] and right == ["short", "long"]
        assert kwargs == dict(padding=True, truncation=True, max_length=512, return_tensors="np")
        return {"input_ids": np.array([[1, 2], [3, 4]], dtype=np.int32)}
    model.tokenizer = tokenize
    def run(outputs, inputs):
        assert outputs == ["logits"] and inputs["input_ids"].dtype == np.int64
        return [np.array([[0.0], [2.0]], dtype=np.float32)]
    model.session = SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="input_ids")], run=run)
    np.testing.assert_allclose(model.predict([["query", "short"], ["query", "long"]]), [0.5, 0.880797], rtol=1e-6)
    assert model.predict([]).size == 0


def test_export_does_not_swap_masks_with_segment_ids(tmp_path):
    class TinyModel(torch.nn.Module):
        def forward(self, input_ids, attention_mask, token_type_ids, return_dict=False):
            scores = (input_ids.sum(1) + 5 * attention_mask.sum(1) + 10 * token_type_ids.sum(1)).float()
            return (scores[:, None],)
    def tokenize(left, right, return_tensors, **kwargs):
        # Hugging Face's dictionary order differs from the forward signature.
        values = dict(input_ids=[[1, 2]], token_type_ids=[[0, 1]], attention_mask=[[1, 0]])
        return {key: torch.tensor(value) if return_tensors == "pt" else np.array(value, dtype=np.int32)
                for key, value in values.items()}
    encoder = SimpleNamespace(tokenizer=tokenize, max_length=512, model=TinyModel(),
                              default_activation_function=torch.nn.Identity(),
                              config=SimpleNamespace(to_json_string=lambda: '{}'))
    model = OnnxReranker(encoder, tmp_path)
    np.testing.assert_allclose(model.predict([["q", "doc"]]), [18.0])
