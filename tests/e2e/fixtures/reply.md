# Agent 回复示例

梯度裁剪（gradient clipping）是一种防止梯度爆炸的技术。它在反向传播之后、参数更新之前，把梯度的范数限制在某个阈值以内。

## 为什么需要它

在训练 Transformer 或 RNN 时，梯度可能会突然变得非常大，导致 loss 出现 NaN。使用 clip_grad_norm_ 可以让训练更加稳定。

The learning rate warmup schedule linearly increases the learning rate during the first few thousand steps.
