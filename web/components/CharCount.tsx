const fr = new Intl.NumberFormat("fr-FR");

/** La borne du schéma `ProjectCreate` n'apparaissait qu'en échec, après
 * l'envoi. Elle se lit maintenant pendant la frappe. */
export function CharCount({ value, max, id }: { value: string; max: number; id: string }) {
  const n = value.length;
  const tone = n > max ? " field__count--over" : n >= max * 0.9 ? " field__count--near" : "";
  return (
    <span className={`field__count${tone}`} id={id}>
      {fr.format(n)} / {fr.format(max)}
    </span>
  );
}
