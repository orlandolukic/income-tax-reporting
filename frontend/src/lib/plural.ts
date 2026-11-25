/** Serbian plural of "firma" after a number: 1 firma, 2 firme, 5 firmi (21 firma, 12 firmi). */
export function companies(n: number): string {
  const tens = n % 100;
  if (n % 10 === 1 && tens !== 11) return `${n} firma`;
  if (n % 10 >= 2 && n % 10 <= 4 && (tens < 12 || tens > 14)) return `${n} firme`;
  return `${n} firmi`;
}

/** The same after "od" (genitive): od 1 firme, od 3 firme, od 165 firmi. */
export function ofCompanies(n: number): string {
  const tens = n % 100;
  if (n % 10 >= 1 && n % 10 <= 4 && (tens < 11 || tens > 14)) return `${n} firme`;
  return `${n} firmi`;
}
