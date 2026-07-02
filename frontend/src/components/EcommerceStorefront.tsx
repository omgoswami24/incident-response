const PRODUCTS = [
  { id: "p1", name: "Wireless Mouse", price: "$24.99" },
  { id: "p2", name: "Mechanical Keyboard", price: "$89.99" },
  { id: "p3", name: "USB-C Hub", price: "$34.99" },
  { id: "p4", name: "Laptop Stand", price: "$42.99" },
];

/** Cosmetic storefront panel — the real "app" being monitored is the
 * ecommerce-app/ git repo the backend analyzes; this is just the visual
 * hook for the demo narrative. */
export function EcommerceStorefront() {
  return (
    <div className="storefront">
      <div className="storefront-header">
        <span className="storefront-logo">🛒 ShopDemo</span>
        <span className="storefront-status">● all systems nominal</span>
      </div>
      <div className="storefront-products">
        {PRODUCTS.map((p) => (
          <div key={p.id} className="storefront-product">
            <div className="storefront-product-thumb" />
            <div className="storefront-product-name">{p.name}</div>
            <div className="storefront-product-price">{p.price}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
