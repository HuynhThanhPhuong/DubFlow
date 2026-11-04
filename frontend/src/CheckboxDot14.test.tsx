/// <reference types="vite/client" />
import editor from "./editor-dot7.css?raw";
import base from "./styles.css?raw";
import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

afterEach(cleanup);

it("aligns the error filter checkbox centre with the sentence number column", () => {
  const selectors = [
    ".studio-app .sentence",
    ".studio-app .line-no",
    ".studio-app .cue-failed-bar",
    '.cue-failed-bar input[type="checkbox"]',
  ];
  const rules = selectors.map((selector) =>
    editor.slice(
      editor.indexOf(selector + " {"),
      editor.indexOf("}", editor.indexOf(selector + " {")) + 1,
    ),
  );
  const start = base.indexOf(".sentence {");
  const style = document.createElement("style");
  style.textContent =
    base.slice(start, base.indexOf("}", start) + 1) + rules.join("\n");
  document.head.append(style);
  try {
    const { container } = render(
      <div className="studio-app">
        <div className="cue-failed-bar">
          <label>
            <input type="checkbox" />
            Câu lỗi/còn trống (1)
          </label>
        </div>
        <div className="sentence">
          <button className="line-no">1</button>
        </div>
      </div>,
    );
    const bar = getComputedStyle(container.querySelector(".cue-failed-bar")!);
    const input = getComputedStyle(container.querySelector("input")!);
    const row = getComputedStyle(container.querySelector(".sentence")!);
    const number = getComputedStyle(container.querySelector(".line-no")!);
    const checkboxCentre =
      parseFloat(bar.paddingLeft) +
      parseFloat(input.marginLeft) +
      parseFloat(input.width) / 2;
    const numberCentre =
      parseFloat(row.borderLeftWidth) +
      parseFloat(row.paddingLeft) +
      parseFloat(number.width) / 2;
    expect(checkboxCentre).toBe(numberCentre);
  } finally {
    style.remove();
  }
});
