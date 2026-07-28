// ============================================================
// PRODUCTOS EN VENTA — FOMO DROP
// ============================================================
// IMPORTANTE: cada producto es una PIEZA ÚNICA. No hay dos iguales,
// no se repone. En cuanto se vende, hay que BORRAR ese bloque entero
// de este archivo (no se pone a 0, se elimina) y volver a subir el
// archivo a GitHub. Así desaparece del sitio para siempre.
//
// CÓMO AÑADIR UN PRODUCTO NUEVO:
//
// 1. Copia un bloque completo (desde { hasta la }, que le sigue) y pégalo
//    justo antes del ] que cierra la lista, al final de este archivo.
// 2. Cambia los datos por los del producto nuevo.
// 3. Sube la foto a la carpeta img/ y pon ese mismo nombre en "imagen".
// 4. Guarda y sube este archivo (products.js) + la foto nueva a GitHub,
//    tal y como hiciste con la carpeta img/ la última vez.
//
// SOLO son obligatorios los campos que terminan en "_es" (español).
// Los campos "_en", "_fr", "_de" son OPCIONALES:
//   - Si los dejas en blanco (""), la web usará el texto en español
//     también cuando alguien vea la página en inglés/francés/alemán.
//   - Si quieres que ese producto se vea traducido en los 4 idiomas,
//     pídeme a mí (Claude) que te lo traduzca y yo relleno esos campos.
//
// "categoria" solo admite estas 3 palabras (van traducidas solas, no
// hace falta que tú las traduzcas):
//   "futbol"  -> Fútbol Vintage / Vintage Football / Football Vintage / Vintage Fußball
//   "denim"   -> Denim Deadstock
//   "otro"    -> Pieza Vintage / Vintage Piece / Pièce Vintage / Vintage-Stück
//
// "talla" es un solo campo (no hace falta traducirlo): pon el valor tal
// cual, por ejemplo "M/L", "S (W32)", "42", etc.
//
// "stock" y "stockTotal" ya NO hace falta ponerlos — como cada pieza es
// única, la web asume 1 de 1 automáticamente y muestra "Pieza única".
// Puedes omitir esas dos líneas al copiar el bloque de ejemplo.
//
// "precioAntes" = precio tachado. Si no quieres mostrar precio tachado,
// pon 0.
// ============================================================

window.PRODUCTS = [

  {
    id: "bayern",
    categoria: "futbol",
    imagen: "img/jersey-bayern.jpg",
    precio: 149,
    precioAntes: 189,
    talla: "M/L",

    nombre_es: "Bayern Múnich 1971/72",
    resumen_es: "Local · Talla M/L · Algodón original",
    descripcion_es: "Camiseta local del Bayern Múnich, temporada 1971/72. Bandas verticales rojo y blanco con el escudo del club bordado en el pecho. Pieza de algodón original de época, corte clásico entallado y costuras de la época sin alterar.",

    nombre_en: "Bayern Munich 1971/72",
    resumen_en: "Home · Size M/L · Original cotton",
    descripcion_en: "Bayern Munich home shirt, 1971/72 season. Vertical red and white stripes with the club crest embroidered on the chest. Original period cotton piece, classic fitted cut, original-era stitching untouched.",

    nombre_fr: "Bayern Munich 1971/72",
    resumen_fr: "Domicile · Taille M/L · Coton d'origine",
    descripcion_fr: "Maillot domicile du Bayern Munich, saison 1971/72. Bandes verticales rouges et blanches avec l'écusson du club brodé sur la poitrine. Pièce en coton d'origine, coupe classique ajustée, coutures d'époque intactes.",

    nombre_de: "Bayern München 1971/72",
    resumen_de: "Heimtrikot · Größe M/L · Original-Baumwolle",
    descripcion_de: "Heimtrikot des FC Bayern München, Saison 1971/72. Vertikale rot-weiße Streifen mit gesticktem Vereinswappen auf der Brust. Original-Baumwollstück aus der Zeit, klassischer, tailliert geschnitten, unveränderte Nähte der Epoche."
  },

  {
    id: "milan",
    categoria: "futbol",
    imagen: "img/jersey-milan.jpg",
    precio: 169,
    precioAntes: 215,
    talla: "L",

    nombre_es: "AC Milan 1995/96 · Cuarta Eq.",
    resumen_es: "Cuarta equipación · Talla L · Poliéster original",
    descripcion_es: "Cuarta equipación del AC Milan 1995/96, patrocinada por Opel. Azul con detalles en rojo y negro y estampado geométrico característico de los 90. Tejido técnico de poliéster original, sin reediciones.",

    nombre_en: "AC Milan 1995/96 · 4th Kit",
    resumen_en: "Fourth kit · Size L · Original polyester",
    descripcion_en: "AC Milan's 1995/96 fourth kit, sponsored by Opel. Blue with red and black details and the geometric print typical of the 90s. Original technical polyester fabric, no reissue.",

    nombre_fr: "AC Milan 1995/96 · 4ème Maillot",
    resumen_fr: "Quatrième maillot · Taille L · Polyester d'origine",
    descripcion_fr: "Quatrième maillot de l'AC Milan 1995/96, sponsorisé par Opel. Bleu avec détails rouge et noir et motif géométrique typique des années 90. Tissu technique en polyester d'origine, sans réédition.",

    nombre_de: "AC Mailand 1995/96 · 4. Trikot",
    resumen_de: "Viertes Trikot · Größe L · Original-Polyester",
    descripcion_de: "Viertes Trikot des AC Mailand 1995/96, gesponsert von Opel. Blau mit roten und schwarzen Details und dem für die 90er typischen geometrischen Muster. Original-Funktionspolyester, keine Neuauflage."
  },

  {
    id: "jeansS",
    categoria: "denim",
    imagen: "img/jeans-501-s.webp",
    precio: 189,
    precioAntes: 249,
    talla: "S (W32)",

    nombre_es: "Levi's 501 Original",
    resumen_es: "Talla S (W32) · Denim crudo sin lavar · Deadstock con etiqueta",
    descripcion_es: "Vaquero Levi's 501 Original en denim crudo sin lavar. Deadstock: nunca ha sido usado, conserva la etiqueta de cartón original y el parche de cuero intacto. Corte recto clásico, tal como salió de fábrica.",

    nombre_en: "Levi's 501 Original",
    resumen_en: "Size S (W32) · Raw, unwashed denim · Deadstock with tag",
    descripcion_en: "Levi's 501 Original in raw, unwashed denim. Deadstock: never worn, still has the original cardboard tag and intact leather patch. Classic straight cut, exactly as it left the factory.",

    nombre_fr: "Levi's 501 Original",
    resumen_fr: "Taille S (W32) · Denim brut non lavé · Deadstock avec étiquette",
    descripcion_fr: "Jean Levi's 501 Original en denim brut non lavé. Deadstock : jamais porté, étiquette carton d'origine et patch en cuir intacts. Coupe droite classique, tel que sorti d'usine.",

    nombre_de: "Levi's 501 Original",
    resumen_de: "Größe S (W32) · Roher, ungewaschener Denim · Deadstock mit Etikett",
    descripcion_de: "Levi's 501 Original aus rohem, ungewaschenem Denim. Deadstock: nie getragen, mit originalem Pappetikett und intaktem Lederpatch. Klassischer gerader Schnitt, genau wie ab Werk."
  },

  {
    id: "jeansL",
    categoria: "denim",
    imagen: "img/jeans-501-l.webp",
    precio: 179,
    precioAntes: 239,
    talla: "L (W34/L32)",

    nombre_es: "Levi's 501 Original",
    resumen_es: "Talla L (W34/L32) · Denim crudo sin lavar · Deadstock con etiqueta",
    descripcion_es: "Vaquero Levi's 501 Original en denim crudo sin lavar. Deadstock: nunca ha sido usado, conserva la etiqueta de cartón y el patch de piel intacto. Corte recto clásico, tal como salió de fábrica.",

    nombre_en: "Levi's 501 Original",
    resumen_en: "Size L (W34/L32) · Raw, unwashed denim · Deadstock with tag",
    descripcion_en: "Levi's 501 Original in raw, unwashed denim. Deadstock: never worn, still has the original cardboard tag and leather patch intact. Classic straight cut, exactly as it left the factory.",

    nombre_fr: "Levi's 501 Original",
    resumen_fr: "Taille L (W34/L32) · Denim brut non lavé · Deadstock avec étiquette",
    descripcion_fr: "Jean Levi's 501 Original en denim brut non lavé. Deadstock : jamais porté, étiquette carton et patch en cuir intacts. Coupe droite classique, tel que sorti d'usine.",

    nombre_de: "Levi's 501 Original",
    resumen_de: "Größe L (W34/L32) · Roher, ungewaschener Denim · Deadstock mit Etikett",
    descripcion_de: "Levi's 501 Original aus rohem, ungewaschenem Denim. Deadstock: nie getragen, mit originalem Pappetikett und Lederpatch intakt. Klassischer gerader Schnitt, genau wie ab Werk."
  }

  // ⬇⬇⬇ AÑADE TU PRODUCTO NUEVO AQUÍ ABAJO, ANTES DEL CORCHETE ⬇⬇⬇
  // Ejemplo mínimo (solo español, funciona igual):
  //
  // ,{
  //   id: "real-madrid-9495",
  //   categoria: "futbol",
  //   imagen: "img/real-madrid-9495.jpg",
  //   precio: 159,
  //   precioAntes: 199,
  //   talla: "M",
  //   nombre_es: "Real Madrid 1994/95",
  //   resumen_es: "Local · Talla M · Algodón original",
  //   descripcion_es: "Camiseta local del Real Madrid, temporada 1994/95. Estado excelente para su edad.",
  //   nombre_en: "", resumen_en: "", descripcion_en: "",
  //   nombre_fr: "", resumen_fr: "", descripcion_fr: "",
  //   nombre_de: "", resumen_de: "", descripcion_de: ""
  // }

];
