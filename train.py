import logging
import os
import sys

from typing import List, Callable, NoReturn, NewType, Any
import dataclasses
from datasets import load_metric, load_from_disk, Dataset, DatasetDict

from transformers import AutoConfig, AutoModelForQuestionAnswering, AutoTokenizer

from transformers import (
    DataCollatorWithPadding,
    EvalPrediction,
    HfArgumentParser,
    TrainingArguments,
    set_seed,
)

from tokenizers import Tokenizer
from tokenizers.models import WordPiece

from utils_qa import postprocess_qa_predictions, check_no_error
from trainer_qa import QuestionAnsweringTrainer
from retrieval import SparseRetrieval

from arguments import ModelArguments, DataTrainingArguments, MyTrainingArguments

import wandb
import torch
import torch.nn as nn

from preprocess import make_datasets

logger = logging.getLogger(__name__)


def main(args):
    model_args, data_args, training_args = args

    print(f"model is from {model_args.model_name_or_path}")
    print(f"data is from {data_args.dataset_name}")

    # logging 설정
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s -    %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # verbosity 설정 : Transformers logger의 정보로 사용합니다 (on main process only)
    logger.info("Training/evaluation parameters %s", training_args)

    # 모델을 초기화하기 전에 난수를 고정합니다.
    set_seed(training_args.seed)

    datasets = load_from_disk(data_args.dataset_name)
    print(datasets)

    config = AutoConfig.from_pretrained(
        model_args.config_name if model_args.config_name is not None else model_args.model_name_or_path,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        model_args.tokenizer_name if model_args.tokenizer_name is not None else model_args.model_name_or_path,
        use_fast=True,
    )
    model = AutoModelForQuestionAnswering.from_pretrained(
        model_args.model_name_or_path,
        from_tf=bool(".ckpt" in model_args.model_name_or_path),
        config=config,
    )

    train()

    # # do_train mrc model 혹은 do_eval mrc model
    # if training_args.do_train or training_args.do_eval:
    #     train(data_args, training_args, model_args, datasets, tokenizer, model)


def train(
    data_args: DataTrainingArguments,
    training_args: MyTrainingArguments,
    model_args: ModelArguments,
    datasets: DatasetDict,
    tokenizer,
    model,
) -> NoReturn:

    # if training_args.do_train:
    #     column_names = datasets["train"].column_names
    # else:
    #     column_names = datasets["validation"].column_names

    # question_column_name = "question" if "question" in column_names else column_names[0]
    # context_column_name = "context" if "context" in column_names else column_names[1]
    # answer_column_name = "answers" if "answers" in column_names else column_names[2]

    # pad_on_right = tokenizer.padding_side == "right"

    # last_checkpoint, max_seq_length = check_no_error(data_args, training_args, datasets, tokenizer)

    # def prepare_train_features(examples):
    #     tokenized_examples = tokenizer(
    #         examples[question_column_name if pad_on_right else context_column_name],
    #         examples[context_column_name if pad_on_right else question_column_name],
    #         truncation="only_second" if pad_on_right else "only_first",
    #         max_length=max_seq_length,
    #         stride=data_args.doc_stride,
    #         return_overflowing_tokens=True,
    #         return_offsets_mapping=True,
    #         return_token_type_ids=False,
    #         padding="max_length" if data_args.pad_to_max_length else False,
    #     )

    #     sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")
    #     offset_mapping = tokenized_examples.pop("offset_mapping")

    #     tokenized_examples["start_positions"] = []
    #     tokenized_examples["end_positions"] = []

    #     for i, offsets in enumerate(offset_mapping):
    #         input_ids = tokenized_examples["input_ids"][i]
    #         cls_index = input_ids.index(tokenizer.cls_token_id)  # cls index

    #         sequence_ids = tokenized_examples.sequence_ids(i)  # token_type_ids

    #         sample_index = sample_mapping[i]
    #         answers = examples[answer_column_name][sample_index]

    #         # answer가 없을 경우 cls_index를 answer로 설정합니다(== example에서 정답이 없는 경우 존재할 수 있음).
    #         if len(answers["answer_start"]) == 0:
    #             tokenized_examples["start_positions"].append(cls_index)
    #             tokenized_examples["end_positions"].append(cls_index)
    #         else:
    #             start_char = answers["answer_start"][0]
    #             end_char = start_char + len(answers["text"][0])

    #             token_start_index = 0
    #             while sequence_ids[token_start_index] != (1 if pad_on_right else 0):
    #                 token_start_index += 1

    #             token_end_index = len(input_ids) - 1
    #             while sequence_ids[token_end_index] != (1 if pad_on_right else 0):
    #                 token_end_index -= 1

    #             # 정답이 span을 벗어났는지 확인합니다(정답이 없는 경우 CLS index로 label되어있음).
    #             if not (
    #                 offsets[token_start_index][0] <= start_char and offsets[token_end_index][1] >= end_char
    #             ):
    #                 tokenized_examples["start_positions"].append(cls_index)
    #                 tokenized_examples["end_positions"].append(cls_index)
    #             else:
    #                 # token_start_index 및 token_end_index를 answer의 끝으로 이동합니다.
    #                 # Note: answer가 마지막 단어인 경우 last offset을 따라갈 수 있습니다(edge case).
    #                 while token_start_index < len(offsets) and offsets[token_start_index][0] <= start_char:
    #                     token_start_index += 1
    #                 tokenized_examples["start_positions"].append(token_start_index - 1)
    #                 while offsets[token_end_index][1] >= end_char:
    #                     token_end_index -= 1
    #                 tokenized_examples["end_positions"].append(token_end_index + 1)

    #     return tokenized_examples

    train_dataset, valid_dataset = make_datasets(datasets, training_args, data_args)

    # if training_args.do_train:
    #     if "train" not in datasets:
    #         raise ValueError("--do_train requires a train dataset")
    #     train_dataset = datasets["train"]

    #     train_dataset = train_dataset.map(
    #         prepare_train_features,
    #         batched=True,
    #         num_proc=data_args.preprocessing_num_workers,
    #         remove_columns=column_names,
    #         load_from_cache_file=not data_args.overwrite_cache,
    #     )

    # def prepare_validation_features(examples):
    #     # truncation과 padding(length가 짧을때만)을 통해 toknization을 진행하며, stride를 이용하여 overflow를 유지합니다.
    #     # 각 example들은 이전의 context와 조금씩 겹치게됩니다.
    #     tokenized_examples = tokenizer(
    #         examples[question_column_name if pad_on_right else context_column_name],
    #         examples[context_column_name if pad_on_right else question_column_name],
    #         truncation="only_second" if pad_on_right else "only_first",
    #         max_length=max_seq_length,
    #         stride=data_args.doc_stride,
    #         return_overflowing_tokens=True,
    #         return_offsets_mapping=True,
    #         return_token_type_ids=False,
    #         padding="max_length" if data_args.pad_to_max_length else False,
    #     )

    #     sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")

    #     # evaluation을 위해, prediction을 context의 substring으로 변환해야합니다.
    #     # corresponding example_id를 유지하고 offset mappings을 저장해야합니다.
    #     tokenized_examples["example_id"] = []

    #     for i in range(len(tokenized_examples["input_ids"])):
    #         sequence_ids = tokenized_examples.sequence_ids(i)
    #         context_index = 1 if pad_on_right else 0

    #         # 하나의 example이 여러개의 span을 가질 수 있습니다.
    #         sample_index = sample_mapping[i]
    #         tokenized_examples["example_id"].append(examples["id"][sample_index])

    #         # Set to None the offset_mapping을 None으로 설정해서 token position이 context의 일부인지 쉽게 판별 할 수 있습니다.
    #         tokenized_examples["offset_mapping"][i] = [
    #             (o if sequence_ids[k] == context_index else None)
    #             for k, o in enumerate(tokenized_examples["offset_mapping"][i])
    #         ]
    #     return tokenized_examples

    # if training_args.do_eval:
    #     eval_dataset = datasets["validation"]

    #     eval_dataset = eval_dataset.map(
    #         prepare_validation_features,
    #         batched=True,
    #         num_proc=data_args.preprocessing_num_workers,
    #         remove_columns=column_names,
    #         load_from_cache_file=not data_args.overwrite_cache,
    #     )

    # Data collator
    # flag가 True이면 이미 max length로 padding된 상태입니다.
    # 그렇지 않다면 data collator에서 padding을 진행해야합니다.
    data_collator = DataCollatorWithPadding(tokenizer, pad_to_multiple_of=8 if training_args.fp16 else None)

    metric = load_metric("squad")

    def compute_metrics(p: EvalPrediction):
        return metric.compute(predictions=p.predictions, references=p.label_ids)

    # Trainer 초기화
    trainer = QuestionAnsweringTrainer(
        model=model,
        args=training_args,
        data_args=data_args,
        train_dataset=train_dataset if training_args.do_train else None,
        eval_dataset=eval_dataset if training_args.do_eval else None,
        eval_examples=datasets["validation"] if training_args.do_eval else None,
        tokenizer=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )

    # Training
    if training_args.do_train:
        if last_checkpoint is not None:
            checkpoint = last_checkpoint
        elif os.path.isdir(model_args.model_name_or_path):
            checkpoint = model_args.model_name_or_path
        else:
            checkpoint = None
        train_result = trainer.train(resume_from_checkpoint=checkpoint)
        trainer.save_model()  # Saves the tokenizer too for easy upload

        metrics = train_result.metrics
        metrics["train_samples"] = len(train_dataset)

        trainer.log_metrics("train", metrics)
        trainer.save_metrics("train", metrics)
        trainer.save_state()

        output_train_file = os.path.join(training_args.output_dir, "train_results.txt")

        with open(output_train_file, "w") as writer:
            logger.info("***** Train results *****")
            for key, value in sorted(train_result.metrics.items()):
                logger.info(f"  {key} = {value}")
                writer.write(f"{key} = {value}\n")

        # State 저장
        trainer.state.save_to_json(os.path.join(training_args.output_dir, "trainer_state.json"))

    # Evaluation
    if training_args.do_eval:
        logger.info("*** Evaluate ***")
        metrics = trainer.evaluate()

        metrics["eval_samples"] = len(eval_dataset)

        trainer.log_metrics("eval", metrics)
        trainer.save_metrics("eval", metrics)


if __name__ == "__main__":

    os.environ["WANDB_DISABLED"] = "true"
    # wandb.init(
    #     project="MRC_baseline",
    #     entity="chungye-mountain-sherpa",
    #     name="default settings",
    #     group=model_args.model_name_or_path
    # )

    parser = HfArgumentParser((ModelArguments, DataTrainingArguments, MyTrainingArguments))

    args = parser.parse_args_into_dataclasses()

    main(args)
