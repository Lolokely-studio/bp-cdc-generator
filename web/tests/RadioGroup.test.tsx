import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { RadioGroup } from "@/components/RadioGroup";

const OPTIONS = [
  { value: "a", render: "Un" },
  { value: "b", render: "Deux" },
  { value: "c", render: "Trois" },
];

function mount(value = "a") {
  const onChange = vi.fn();
  render(<RadioGroup label="Un choix" value={value} onChange={onChange} options={OPTIONS} />);
  return { onChange };
}

/** Un groupe qui retient son choix : les cas qui enchaînent deux flèches
 * ont besoin que le parent rende la nouvelle sélection. */
function Stateful() {
  const [value, setValue] = useState("a");
  return <RadioGroup label="Un choix" value={value} onChange={setValue} options={OPTIONS} />;
}

describe("le groupe à choix unique", () => {
  it("n'offre qu'un seul arrêt de tabulation", () => {
    mount("b");
    expect(screen.getByRole("radio", { name: "Deux" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Un" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("radio", { name: "Trois" })).toHaveAttribute("tabindex", "-1");
  });

  it("coche l'option courante, et elle seule", () => {
    mount("b");
    expect(screen.getByRole("radio", { name: "Deux" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Un" })).toHaveAttribute("aria-checked", "false");
  });

  it("avance à la flèche droite et boucle à la fin", async () => {
    const user = userEvent.setup();
    const { onChange } = mount("c");
    screen.getByRole("radio", { name: "Trois" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("recule à la flèche gauche et boucle au début", async () => {
    const user = userEvent.setup();
    const { onChange } = mount("a");
    screen.getByRole("radio", { name: "Un" }).focus();
    await user.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenCalledWith("c");
  });

  it("emmène le focus avec la sélection", async () => {
    // Sans cela, une deuxième flèche repartirait de l'option qu'on vient
    // de quitter, et on ne dépasserait jamais la voisine.
    const user = userEvent.setup();
    render(<Stateful />);
    screen.getByRole("radio", { name: "Un" }).focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Trois" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Trois" })).toHaveFocus();
  });

  it("choisit au clic", async () => {
    const { onChange } = mount();
    await userEvent.setup().click(screen.getByRole("radio", { name: "Trois" }));
    expect(onChange).toHaveBeenCalledWith("c");
  });
});
