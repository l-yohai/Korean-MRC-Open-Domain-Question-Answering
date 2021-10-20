import os

from datasets import load_from_disk, set_caching_enabled
from transformers import (
    AutoConfig,
    AutoTokenizer,
    AutoModelForQuestionAnswering,
    DataCollatorWithPadding,
    HfArgumentParser,
    Trainer,
    set_seed,
)

import wandb

from arguments import SettingsArguments, Arguments
from process import preprocess
from metric import compute_metrics
from utils import send_along
from models.lstm_roberta import LSTMRobertaForQuestionAnswering


def train(settings, args):
    args.config = AutoConfig.from_pretrained(settings.pretrained_model_name_or_path)
    args.tokenizer = AutoTokenizer.from_pretrained(settings.pretrained_model_name_or_path)
    model = AutoModelForQuestionAnswering.from_pretrained(
        settings.pretrained_model_name_or_path, config=args.config
    )
    # model = LSTMRobertaForQuestionAnswering(settings.pretrained_model_name_or_path, config=args.config)

    data_collator = DataCollatorWithPadding(
        tokenizer=args.tokenizer, pad_to_multiple_of=args.pad_to_multiple_of if args.fp16 else None
    )
    args.dataset = load_from_disk(settings.trainset_path)

    train_dataset = args.dataset["train"]
    column_names = train_dataset.column_names
    train_dataset = train_dataset.map(
        send_along(preprocess, sent_along=args),
        batched=True,
        num_proc=settings.num_proc,
        remove_columns=column_names,
        load_from_cache_file=settings.load_from_cache_file,
    )

    eval_dataset = args.dataset["validation"]
    eval_dataset = eval_dataset.map(
        send_along(preprocess, sent_along=args),
        batched=True,
        num_proc=settings.num_proc,
        remove_columns=column_names,
        load_from_cache_file=settings.load_from_cache_file,
    )
    args.processed_eval_dataset = eval_dataset

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=args.tokenizer,
        data_collator=data_collator,
        compute_metrics=send_along(compute_metrics, sent_along=args),
    )
    trainer.train()
    trainer.save_model()


if __name__ == "__main__":
    os.environ["WANDB_DISABLED"] = "true"
    parser = HfArgumentParser((SettingsArguments, Arguments))
    settings, args = parser.parse_args_into_dataclasses()
    set_seed(args.seed)
    set_caching_enabled(False)

    # wandb.login()
    # wandb.init(
    #     project="lstm_roberta_conv1d",
    #     entity="chungye-mountain-sherpa",
    #     name=f'base: {args.pretrained_model_name_or_path}',
    #     group='lstm_depth_6',
    # )
    train(settings, args)
