"""FP32 ONNX execution of the existing cross-encoder, with identical tokenization."""
import hashlib
import os
from pathlib import Path

import numpy as np
import torch
import onnxruntime as ort
from filelock import FileLock


class OnnxReranker:
    def __init__(self, encoder, cache_dir, threads=4):
        self.tokenizer = encoder.tokenizer
        self.max_length = encoder.max_length
        self.activation = encoder.default_activation_function
        encoder.model.eval()
        # Weight/content identity prevents stale exports after a model upgrade.
        digest = hashlib.sha256(str(torch.__version__).encode())
        digest.update(encoder.config.to_json_string().encode())
        for name, value in encoder.model.state_dict().items():
            digest.update(name.encode())
            digest.update(value.detach().cpu().numpy().tobytes())
        directory = Path(cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"reranker-fp32-v2-{digest.hexdigest()[:24]}.onnx"
        with FileLock(str(path) + ".lock"):
            if not path.exists():
                tokens = self.tokenizer(["medical"], ["medical information"], padding=True,
                                        truncation=True, max_length=self.max_length, return_tensors="pt")
                names = ["input_ids", "attention_mask", "token_type_ids"]
                class ExportModel(torch.nn.Module):
                    def __init__(self, model):
                        super().__init__()
                        self.model = model
                    def forward(self, input_ids, attention_mask, token_type_ids):
                        return self.model(input_ids=input_ids, attention_mask=attention_mask,
                                          token_type_ids=token_type_ids, return_dict=False)[0]
                temporary = path.with_suffix(f".{os.getpid()}.tmp.onnx")
                try:
                    torch.onnx.export(ExportModel(encoder.model).eval(), tuple(tokens[n] for n in names),
                                      str(temporary), input_names=names, output_names=["logits"],
                                      dynamic_axes={**{n: {0: "batch", 1: "sequence"} for n in names},
                                                    "logits": {0: "batch"}}, opset_version=17)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])

    def predict(self, pairs):
        if not pairs:
            return np.array([], dtype=np.float32)
        tokens = self.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], padding=True,
                                truncation=True, max_length=self.max_length, return_tensors="np")
        inputs = {item.name: np.asarray(tokens[item.name], dtype=np.int64)
                  for item in self.session.get_inputs()}
        logits = self.session.run(["logits"], inputs)[0]
        return self.activation(torch.from_numpy(logits)).numpy().reshape(-1)
