import { VAT } from "../utils";

// vatRate: VAT.EXEMPT = basic food staple (no VAT), VAT.STANDARD = 16%, VAT.FUEL = 8%
export const products = [
  // Fruits — standard VAT (processed/packaged)
  { id: 1,  name: "Bananas (1kg)",       price: 120, category: "Fruits",     stock: 40, icon: "bi-emoji-smile", vatRate: VAT.STANDARD },
  { id: 2,  name: "Apples (1kg)",        price: 250, category: "Fruits",     stock: 18, icon: "bi-apple",       vatRate: VAT.STANDARD },
  { id: 3,  name: "Pineapple",           price: 150, category: "Fruits",     stock: 8,  icon: "bi-tree",        vatRate: VAT.STANDARD },

  // Vegetables — standard VAT
  { id: 4,  name: "Tomatoes (1kg)",      price: 90,  category: "Vegetables", stock: 25, icon: "bi-flower2",     vatRate: VAT.STANDARD },
  { id: 5,  name: "Sukuma wiki (bunch)", price: 30,  category: "Vegetables", stock: 60, icon: "bi-flower1",     vatRate: VAT.STANDARD },
  { id: 6,  name: "Carrots (1kg)",       price: 110, category: "Vegetables", stock: 0,  icon: "bi-flower3",     vatRate: VAT.STANDARD },

  // Dairy — raw milk is exempt; packaged milk is standard
  { id: 7,  name: "Fresh Milk 500ml",    price: 65,  category: "Dairy",      stock: 60, icon: "bi-cup-hot",     vatRate: VAT.EXEMPT   },
  { id: 8,  name: "Eggs (tray of 30)",   price: 480, category: "Dairy",      stock: 14, icon: "bi-egg",         vatRate: VAT.EXEMPT   },

  // Bakery — bread is VAT-exempt under Kenya law
  { id: 9,  name: "Bread (400g)",        price: 70,  category: "Bakery",     stock: 30, icon: "bi-bag-heart",   vatRate: VAT.EXEMPT   },
  { id: 10, name: "Mandazi (6 pack)",    price: 60,  category: "Bakery",     stock: 22, icon: "bi-bag",         vatRate: VAT.STANDARD },

  // Drinks — standard VAT
  { id: 11, name: "Mineral Water 1L",    price: 80,  category: "Drinks",     stock: 90, icon: "bi-droplet-fill", vatRate: VAT.STANDARD },
  { id: 12, name: "Soda 500ml",          price: 70,  category: "Drinks",     stock: 5,  icon: "bi-cup-straw",   vatRate: VAT.STANDARD },

  // Household — standard VAT
  { id: 13, name: "Dish Soap 500ml",     price: 190, category: "Household",  stock: 16, icon: "bi-stars",       vatRate: VAT.STANDARD },
  { id: 14, name: "Toilet Paper (4pk)",  price: 220, category: "Household",  stock: 33, icon: "bi-house-check", vatRate: VAT.STANDARD },
];
