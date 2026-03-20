import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";
import { getAuth } from "firebase/auth";

// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyDP9NIXm9hIzDGQ3G9FS1TpZQdVnGq3CCE",
  authDomain: "iot-project-95f1e.firebaseapp.com",
  projectId: "iot-project-95f1e",
  storageBucket: "iot-project-95f1e.firebasestorage.app",
  messagingSenderId: "219565334033",
  appId: "1:219565334033:web:95eb6cf79d4672d46e9bb0",
  measurementId: "G-QC023Z3WRS"
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
export const auth = getAuth(app);
