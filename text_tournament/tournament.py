from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import permutations
from typing import Literal

import click
import instructor
import polars as pl
import yaml
from dotenv import load_dotenv
from litellm import completion
from pydantic import BaseModel
from tqdm import tqdm

load_dotenv()


class Rating(BaseModel):
    class Config:
        extra = "allow"

    reason: str
    preferred: Literal[1, 2]


client = instructor.from_litellm(completion)


def rate(model: str, label: str, competitors: list[str], attribute: str) -> dict:
    rating = client.chat.completions.create(
        model=model,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": f"""Compare the following two {label}: {competitors[0]} and \
                {competitors[1]}. Which is better in regard to {attribute} and why?""",
            }
        ],
        response_model=Rating,
        temperature=0.9,
    )

    return {
        "winner": competitors[rating.preferred - 1],
        "loser": competitors[rating.preferred % 2],
        "attribute": attribute,
        "reason": rating.reason,
    }


# Make all possible comparisons, in both directions
def prep_comparisons(
    competitors: tuple[str, str],
    attributes: str,
    label: str,
    model: str = "gpt-4o-mini",
) -> list[dict]:
    out = []

    for pair in permutations(competitors, 2):
        for attr in attributes:
            out.append(
                {
                    "competitors": list(pair),
                    "attribute": attr,
                    "label": label,
                    "model": model,
                }
            )

    return out


# Use ThreadPoolExecutor to perform ratings
def get_results(comparison_list: list[dict], threads: int) -> pl.DataFrame:
    assert len(comparison_list) > 0, "No comparisons to rate"
    assert threads > 0, "Number of threads must be greater than 0"

    results = []
    with ThreadPoolExecutor(max_workers=threads) as executor:
        # Submit all tasks
        future_to_comparison = {
            executor.submit(rate, **comparison): comparison
            for comparison in comparison_list
        }

        # Process results as they complete
        for future in tqdm(
            as_completed(future_to_comparison), total=len(comparison_list)
        ):
            comparison = future_to_comparison[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                print(f"Rating for {comparison} generated an exception: {exc}")

    return pl.DataFrame(results)


@click.command()
@click.option(
    "--competitors",
    "-c",
    type=str,
    multiple=True,
    help="A list 2 to 24 competitors to compare",
)
@click.option(
    "--attribute",
    "-a",
    type=str,
    multiple=True,
    help="A list of attribute to compare",
)
@click.option(
    "--label",
    type=str,
    help="The label for the items being compared, e.g. 'companies' or 'products'",
)
@click.option(
    "--filepath",
    type=str,
    help="The file to write the results to",
)
@click.option(
    "--model",
    type=str,
    default="gpt-4o-mini",
    help="The model to use for rating",
)
@click.option(
    "--threads",
    type=int,
    default=32,
    help="The number of parallel model completions to run",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to a YAML configuration file",
)
def main(
    competitors: set[str],
    attribute: set[str],
    label: str,
    filepath: str,
    model: str,
    threads: int,
    config: str,
) -> None:
    """
    Conduct a tournament-style comparison of a list of competitors based on a list of attributes.
    """
    if config:
        with open(config, "r") as file:
            yaml_config = yaml.safe_load(file)

        competitors = yaml_config.get("competitors", competitors)
        attributes = yaml_config.get("attributes", attribute)
        label = yaml_config.get("label", label)
        filepath = yaml_config.get("out_file", filepath)
        model = yaml_config.get("model", model)
        threads = yaml_config.get("threads", threads)

    assert len(competitors) > 1, "At least two competitors must be provided"
    assert len(competitors) <= 24, "No more than 24 competitors can be provided"

    comparison_list = prep_comparisons(
        competitors=tuple(competitors), attributes=attributes, label=label, model=model
    )
    results = get_results(comparison_list, threads=threads)
    results.write_csv(filepath)
    print(f"Results written to {filepath}")


if __name__ == "__main__":
    main()
