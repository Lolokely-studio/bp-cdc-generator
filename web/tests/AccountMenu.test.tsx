import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AccountMenu } from "@/components/AccountMenu";

const mount = (onLogout = vi.fn()) => {
  render(<AccountMenu email="lucie@exemple.fr" onLogout={onLogout} />);
  return { button: screen.getByRole("button", { expanded: false }), onLogout };
};

describe("le menu du compte", () => {
  it("garde l'adresse et la déconnexion fermées tant qu'on n'a pas cliqué", () => {
    mount();
    expect(screen.queryByText("lucie@exemple.fr")).toBeNull();
    expect(screen.queryByRole("button", { name: "Se déconnecter" })).toBeNull();
  });

  it("ouvre au clic, et annonce qu'il est ouvert", async () => {
    const { button } = mount();
    await userEvent.setup().click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("lucie@exemple.fr")).toBeInTheDocument();
  });

  it("ferme à Échap et rend le focus au bouton", async () => {
    const user = userEvent.setup();
    const { button } = mount();
    await user.click(button);
    // Le focus doit d'abord quitter le bouton. Sinon l'assertion finale est
    // vraie même quand le code ne rend rien : le clic d'ouverture l'avait
    // déjà posé là. C'est aussi le vrai parcours au clavier — on entre dans
    // le menu, on fait Échap, on veut retrouver le déclencheur.
    screen.getByRole("button", { name: "Se déconnecter" }).focus();
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("ferme au clic hors de lui", async () => {
    const user = userEvent.setup();
    const { button } = mount();
    await user.click(button);
    await user.click(document.body);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("déconnecte", async () => {
    const user = userEvent.setup();
    const { button, onLogout } = mount();
    await user.click(button);
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
    const removeListenerSpy = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(<AccountMenu email="lucie@exemple.fr" onLogout={vi.fn()} />);
    await user.click(screen.getByRole("button", { expanded: false }));
    unmount();
    expect(removeListenerSpy).toHaveBeenCalledWith("mousedown", expect.any(Function));
    removeListenerSpy.mockRestore();
  });
});
