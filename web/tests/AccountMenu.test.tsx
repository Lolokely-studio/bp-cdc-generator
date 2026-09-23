import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AccountMenu } from "@/components/AccountMenu";

const monte = (onLogout = vi.fn()) => {
  render(<AccountMenu email="lucie@exemple.fr" onLogout={onLogout} />);
  return { bouton: screen.getByRole("button", { expanded: false }), onLogout };
};

describe("le menu du compte", () => {
  it("garde l'adresse et la déconnexion fermées tant qu'on n'a pas cliqué", () => {
    monte();
    expect(screen.queryByText("lucie@exemple.fr")).toBeNull();
    expect(screen.queryByRole("button", { name: "Se déconnecter" })).toBeNull();
  });

  it("ouvre au clic, et annonce qu'il est ouvert", async () => {
    const { bouton } = monte();
    await userEvent.setup().click(bouton);
    expect(bouton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("lucie@exemple.fr")).toBeInTheDocument();
  });

  it("ferme à Échap et rend le focus au bouton", async () => {
    const user = userEvent.setup();
    const { bouton } = monte();
    await user.click(bouton);
    // Le focus doit d'abord quitter le bouton. Sinon l'assertion finale est
    // vraie même quand le code ne rend rien : le clic d'ouverture l'avait
    // déjà posé là. C'est aussi le vrai parcours au clavier — on entre dans
    // le menu, on fait Échap, on veut retrouver le déclencheur.
    screen.getByRole("button", { name: "Se déconnecter" }).focus();
    await user.keyboard("{Escape}");
    expect(bouton).toHaveAttribute("aria-expanded", "false");
    expect(bouton).toHaveFocus();
  });

  it("ferme au clic hors de lui", async () => {
    const user = userEvent.setup();
    const { bouton } = monte();
    await user.click(bouton);
    await user.click(document.body);
    expect(bouton).toHaveAttribute("aria-expanded", "false");
  });

  it("déconnecte", async () => {
    const user = userEvent.setup();
    const { bouton, onLogout } = monte();
    await user.click(bouton);
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(onLogout).toHaveBeenCalledOnce();
  });

  // Trou signalé par la tâche : rien ne faisait échouer un composant qui
  // oublierait de retirer son écouteur de clic au démontage. Un clic
  // laissé après coup ne lève rien en React 19 (la mise à jour d'un
  // composant démonté est simplement ignorée) : c'est l'écouteur lui-même
  // qu'il faut voir partir.
  it("retire son écouteur de clic hors de lui en démontant", async () => {
    const user = userEvent.setup();
    const retrait = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(<AccountMenu email="lucie@exemple.fr" onLogout={vi.fn()} />);
    await user.click(screen.getByRole("button", { expanded: false }));
    unmount();
    expect(retrait).toHaveBeenCalledWith("mousedown", expect.any(Function));
    retrait.mockRestore();
  });
});
